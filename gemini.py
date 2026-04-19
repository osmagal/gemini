"""
gemini.py — Módulo de extração de dados de PDF via Gemini.

API pública:
    extract_from_pdf(pdf_path, user_prompt, vars_list, show_browser) -> dict | list

Estratégias de envio (em cascata):
  1. Upload nativo do PDF — Gemini processa o arquivo diretamente (sem limite de chars)
  2. Conversa multi-turno  — documento em partes → disparo do JSON
"""

import json
import re
import sys
import time
from pathlib import Path

import pdfplumber
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from gemini_shared import (
    GEMINI_URL,
    DEFAULT_TIMEOUT,
    CHUNK_SIZE,
    create_browser_context,
    wait_for_input,
    focus_input,
    inject_text,
    send_message,
    wait_for_response,
    send_multiturn,
    chunk_text,
    apply_vars,
)

# ---------------------------------------------------------------------------
# Constantes do módulo
# ---------------------------------------------------------------------------
UPLOAD_BUTTON_SELECTORS = [
    "button[aria-label*='Upload']",
    "button[aria-label*='Adicionar']",
    "button[aria-label*='Attach']",
    "button[aria-label*='file']",
    "button[aria-label*='arquivo']",
    "[data-test-id='attachment-button']",
    "button.upload-button",
    "mat-icon-button[mattooltip*='upload' i]",
    "button[aria-label*='More options']",
    "button[aria-label*='Mais opções']",
    "button.input-pills-button",
]

JSON_INSTRUCTION = (
    "IMPORTANTE: Responda EXCLUSIVAMENTE com um objeto JSON válido. "
    "Sem texto antes ou depois. Sem blocos markdown (```). "
    "Inicie com { e termine com }."
)


# ---------------------------------------------------------------------------
# Extração de texto do PDF
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: str) -> str:
    """Extrai texto completo do PDF página a página via pdfplumber."""
    path = Path(pdf_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Arquivo não é PDF: {pdf_path}")

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[Página {i}]\n{text}")

    if not pages:
        raise ValueError(
            "Nenhum texto extraível no PDF. "
            "O arquivo pode ser baseado em imagens (OCR necessário)."
        )
    return "\n\n".join(pages)


# ---------------------------------------------------------------------------
# Helpers de parsing de JSON
# ---------------------------------------------------------------------------

def extract_json_from_text(text: str) -> dict | list:
    """Extrai JSON de uma string, mesmo que contenha texto em volta."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    raise ValueError(
        f"JSON não encontrado na resposta.\nResposta recebida:\n{text[:500]}..."
    )


# ---------------------------------------------------------------------------
# Estratégia 1: Upload nativo do PDF
# ---------------------------------------------------------------------------

def _try_upload_strategy(page, pdf_path: str, user_prompt: str) -> str | None:
    """
    Tenta fazer upload do PDF diretamente no Gemini.
    Retorna a resposta do modelo, ou None se o upload não for possível.
    """
    print("[RPA] Estratégia 1: upload nativo do PDF...", file=sys.stderr)
    abs_path = str(Path(pdf_path).resolve())

    # a) input[type=file] direto (geralmente hidden no DOM)
    file_input = page.locator("input[type='file']").first
    try:
        file_input.wait_for(state="attached", timeout=3_000)
        file_input.set_input_files(abs_path)
        print("[RPA] Arquivo enviado via input[type=file].", file=sys.stderr)
        time.sleep(0.5)
        return _prompt_after_upload(page, user_prompt)
    except Exception:
        pass

    # b) Botões de upload que abrem file chooser
    for sel in UPLOAD_BUTTON_SELECTORS:
        try:
            btn = page.locator(sel).first
            if not btn.is_visible(timeout=2_000):
                continue
            with page.expect_file_chooser(timeout=5_000) as fc_info:
                btn.click()
            fc_info.value.set_files(abs_path)
            print(f"[RPA] Arquivo enviado via '{sel}'.", file=sys.stderr)
            time.sleep(0.5)
            return _prompt_after_upload(page, user_prompt)
        except Exception:
            continue

    print("[RPA] Upload nativo não disponível — usando multi-turno.", file=sys.stderr)
    return None


def _prompt_after_upload(page, user_prompt: str) -> str:
    """Aguarda o Gemini processar o arquivo e envia o prompt de análise."""
    for _ in range(50):
        time.sleep(0.4)
        uploading = page.evaluate("""() => {
            const el = document.querySelector(
                '.upload-progress, .file-uploading, [aria-label*="uploading"], [role="progressbar"]'
            );
            return !!el;
        }""")
        if not uploading:
            break

    time.sleep(0.5)
    final_prompt = f"{JSON_INSTRUCTION}\n\n{user_prompt}"
    focus_input(page)
    inject_text(page, final_prompt)
    send_message(page)
    print("[RPA] Prompt enviado. Aguardando análise do documento...", file=sys.stderr)
    return wait_for_response(page)


# ---------------------------------------------------------------------------
# Estratégia 2: Multi-turno (documento em partes)
# ---------------------------------------------------------------------------

def _multiturn_strategy(page, pdf_text: str, user_prompt: str) -> str:
    """Envia o documento em partes e dispara a análise no turno final."""
    chunks = chunk_text(pdf_text, CHUNK_SIZE)
    trigger = f"ANALISAR\n\n{JSON_INSTRUCTION}\n\n{user_prompt}"
    # Substitui o trigger no send_multiturn para incluir o prompt completo no turno final
    # Envia os chunks normalmente e no turno final manda o prompt completo
    n = len(chunks)
    print(
        f"[RPA] Estratégia 2: multi-turno — {n} parte(s) de ~{CHUNK_SIZE:,} chars.",
        file=sys.stderr,
    )

    # Turno 0: instrução
    intro = (
        f"Vou te enviar um documento dividido em {n} parte(s). "
        "Leia cada parte sem responder. "
        "Só responda quando eu enviar 'ANALISAR'. "
        "Confirme com apenas 'OK'."
    )
    focus_input(page)
    inject_text(page, intro)
    send_message(page)
    from gemini_shared import wait_for_ack
    wait_for_ack(page, timeout=30)

    # Turnos 1..N: partes do documento
    for i, chunk in enumerate(chunks, 1):
        msg = f"PARTE {i}/{n}:\n\n{chunk}"
        if i == n:
            msg += "\n\n[FIM DO DOCUMENTO]"
        msg += "\n\nConfirme com 'OK'."
        print(f"[RPA] Enviando parte {i}/{n} ({len(chunk):,} chars)...", file=sys.stderr)
        focus_input(page)
        inject_text(page, msg)
        send_message(page)
        wait_for_ack(page, timeout=45)

    # Turno final: dispara análise com o prompt completo
    print("[RPA] Disparando análise e aguardando JSON...", file=sys.stderr)
    focus_input(page)
    inject_text(page, trigger)
    send_message(page)
    return wait_for_response(page)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def run(
    pdf_path: str,
    user_prompt: str,
    show_browser: bool = False,
    progress_callback=None,
) -> str:
    """
    Abre o Gemini, envia o PDF e o prompt, retorna a resposta bruta do modelo.
    Tenta upload nativo primeiro; usa multi-turno como fallback.
    """
    def update(msg, percent):
        if progress_callback:
            progress_callback(msg, percent)

    with sync_playwright() as p:
        update("Iniciando navegador...", 5)
        ctx = create_browser_context(p, headless=False)
        page = ctx.new_page()
        try:
            update("Abrindo Gemini...", 10)
            page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            wait_for_input(page)
            
            update("Extraindo texto do PDF...", 20)
            pdf_text = extract_pdf_text(pdf_path)
            
            # Estratégia multi-turno com progresso detalhado
            chunks = chunk_text(pdf_text, CHUNK_SIZE)
            n = len(chunks)
            update(f"Preparando {n} partes para envio...", 30)
            
            # Turno 0: instrução
            intro = (
                f"Vou te enviar um documento dividido em {n} parte(s). "
                "Leia cada parte sem responder. "
                "Só responda quando eu enviar 'ANALISAR'. "
                "Confirme com apenas 'OK'."
            )
            update("Enviando instruções iniciais...", 35)
            focus_input(page)
            inject_text(page, intro)
            send_message(page)
            from gemini_shared import wait_for_ack
            wait_for_ack(page, timeout=30)

            # Turnos 1..N: partes do documento
            for i, chunk in enumerate(chunks, 1):
                msg = f"PARTE {i}/{n}:\n\n{chunk}"
                if i == n:
                    msg += "\n\n[FIM DO DOCUMENTO]"
                msg += "\n\nConfirme com 'OK'."
                
                percent = 35 + int((i / n) * 45) # 35% a 80%
                update(f"Enviando parte {i}/{n}...", percent)
                
                focus_input(page)
                inject_text(page, msg)
                send_message(page)
                wait_for_ack(page, timeout=45)

            # Turno final: dispara análise com o prompt completo
            update("Solicitando análise final...", 85)
            trigger = f"ANALISAR\n\n{JSON_INSTRUCTION}\n\n{user_prompt}"
            focus_input(page)
            inject_text(page, trigger)
            send_message(page)
            
            update("Aguardando resposta do Gemini...", 90)
            response = wait_for_response(page)
            update("Concluído!", 100)

            return response
        except PlaywrightTimeout as e:
            raise RuntimeError(
                f"Timeout no Gemini. Verifique se está logado na conta Google.\n{e}"
            ) from e
        finally:
            ctx.close()


def extract_from_pdf(
    pdf_path: str,
    user_prompt: str,
    vars_list: list[str] | None = None,
    show_browser: bool = False,
    progress_callback=None,
) -> dict | list:
    """
    Extrai dados estruturados de um PDF via Gemini e retorna como dict/list.

    Args:
        pdf_path:    Caminho para o arquivo PDF.
        user_prompt: Instruções de extração (o que extrair e em que formato).
        vars_list:   Lista de substituições no formato ["chave=valor", ...].
        show_browser: Se True, exibe o navegador durante a execução.

    Returns:
        dict ou list com os dados extraídos, conforme retornado pelo Gemini.

    Raises:
        FileNotFoundError: Se o PDF não existir.
        RuntimeError: Se houver falha na comunicação com o Gemini.
        ValueError: Se a resposta não contiver JSON válido.
    """
    prompt = apply_vars(user_prompt, vars_list)

    pdf = Path(pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")

    print(
        f"[gemini] PDF: {pdf.name} ({pdf.stat().st_size // 1024} KB)",
        file=sys.stderr,
    )

    raw_response = run(
        str(pdf), prompt, show_browser=show_browser, progress_callback=progress_callback
    )
    return extract_json_from_text(raw_response)
