"""
gemini_shared.py — Primitivas Playwright e utilitários compartilhados entre gemini.py e gemini_code_python.py.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
GEMINI_URL = "https://gemini.google.com/app"

DEFAULT_TIMEOUT   = 60_000   # ms – timeout geral para elementos
SEND_TIMEOUT      = 10_000   # ms – timeout para botão de envio
RESPONSE_MAX_WAIT = 300      # s  – máximo aguardando resposta
RESPONSE_POLL     = 2        # s  – intervalo de polling
STABLE_CYCLES     = 3        # ciclos estáveis = resposta completa
CHUNK_SIZE        = 28_000   # chars por turno no multi-turno

INPUT_SELECTORS = [
    "rich-textarea div[contenteditable='true']",
    "rich-textarea",
    "div[contenteditable='true'][data-placeholder]",
    "div.ql-editor[contenteditable='true']",
    "textarea",
]

SEND_SELECTORS = [
    "button[aria-label='Send message']",
    "button[aria-label='Enviar mensagem']",
    "button[aria-label*='Send']",
    "button[aria-label*='Enviar']",
    "button[data-test-id='send-button']",
    "button[jsname='Qx7uuf']",
]

RESPONSE_SELECTORS = [
    "model-response .markdown",
    "model-response",
    ".model-response-text",
    "message-content.model-response-text",
    "[data-message-author-role='model']",
]


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

def create_browser_context(playwright, headless: bool):
    """Cria e retorna um contexto persistente do Chromium."""
    user_data_dir = Path.home() / ".gemini_rpa_profile"
    user_data_dir.mkdir(exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        str(user_data_dir),
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
        permissions=["clipboard-read", "clipboard-write"],
    )


# ---------------------------------------------------------------------------
# Primitivas de interação com o Gemini
# ---------------------------------------------------------------------------

def wait_for_input(page) -> None:
    """Aguarda o campo de entrada do Gemini ficar visível."""
    for sel in INPUT_SELECTORS:
        try:
            page.wait_for_selector(sel, timeout=DEFAULT_TIMEOUT, state="visible")
            return
        except PlaywrightTimeout:
            continue
    raise RuntimeError(
        "Campo de entrada não encontrado. Verifique se está logado no Gemini."
    )


def focus_input(page) -> bool:
    """Clica no campo de entrada. Retorna True se conseguiu."""
    for sel in INPUT_SELECTORS:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=4_000)
            el.click()
            return True
        except Exception:
            continue
    return False


def inject_text(page, text: str) -> None:
    """
    Injeta texto no campo de entrada via Clipboard API do navegador + Ctrl+V.
    Funciona para textos de qualquer tamanho.
    """
    page.evaluate("async (t) => { await navigator.clipboard.writeText(t); }", text)
    time.sleep(0.3)
    page.keyboard.press("Control+a")
    time.sleep(0.2)
    page.keyboard.press("Delete")
    time.sleep(0.2)
    page.keyboard.press("Control+v")
    # Espera proporcional ao tamanho do texto
    time.sleep(max(1.5, min(6, len(text) / 15_000)))


def send_message(page) -> None:
    """Clica no botão de envio ou pressiona Enter."""
    for sel in SEND_SELECTORS:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=SEND_TIMEOUT)
            btn.click()
            return
        except Exception:
            continue
    page.keyboard.press("Enter")


def is_generating(page) -> bool:
    """Verifica se o Gemini ainda está gerando a resposta."""
    for sel in (
        "button[aria-label*='Stop']",
        "button[aria-label*='Parar']",
        ".loading-indicator",
        ".thinking-indicator",
        "mat-progress-spinner",
    ):
        try:
            if page.locator(sel).first.is_visible(timeout=400):
                return True
        except Exception:
            continue
    return False


def get_response_text(page, prefer_code_blocks: bool = False) -> str:
    """
    Extrai o texto da última resposta do modelo.

    Args:
        prefer_code_blocks: Se True, tenta primeiro capturar blocos <pre>/<code>
                            preservando indentação (útil para respostas com código Python).
                            Se False, usa inner_text() padrão (útil para JSON).
    """
    if prefer_code_blocks:
        try:
            code_text = page.evaluate("""() => {
                const responses = [
                    ...document.querySelectorAll('[data-message-author-role="model"]'),
                    ...document.querySelectorAll('model-response'),
                    ...document.querySelectorAll('.model-response-text'),
                ];
                if (responses.length === 0) return null;
                const last = responses[responses.length - 1];

                // Coleta TODOS os blocos <pre> preservando ordem e indentação
                const pres = last.querySelectorAll('pre');
                if (pres.length > 0) {
                    const parts = [];
                    pres.forEach(pre => {
                        const t = pre.innerText || pre.textContent || '';
                        if (t.trim()) parts.push(t);
                    });
                    return parts.join('\\n\\n');
                }
                // Fallback para <code>
                const codes = last.querySelectorAll('code');
                if (codes.length > 0) {
                    const parts = [];
                    codes.forEach(c => {
                        const t = c.innerText || c.textContent || '';
                        if (t.trim()) parts.push(t);
                    });
                    return parts.join('\\n\\n');
                }
                return null;
            }""")
            if code_text and code_text.strip():
                return code_text.strip()
        except Exception:
            pass

    # Extração padrão via inner_text()
    for sel in RESPONSE_SELECTORS:
        try:
            els = page.locator(sel).all()
            if els:
                text = els[-1].inner_text(timeout=2_000)
                if text and text.strip():
                    return text.strip()
        except Exception:
            continue

    # Fallback via JS innerText
    try:
        result = page.evaluate("""() => {
            const sets = [
                document.querySelectorAll('[data-message-author-role="model"]'),
                document.querySelectorAll('model-response'),
                document.querySelectorAll('.model-response-text'),
            ];
            for (const s of sets) {
                if (s.length > 0) return s[s.length - 1].innerText || '';
            }
            return '';
        }""")
        return (result or "").strip()
    except Exception:
        return ""


def wait_for_response(
    page,
    max_wait: int = RESPONSE_MAX_WAIT,
    stable_cycles: int = STABLE_CYCLES,
    prefer_code_blocks: bool = False,
) -> str:
    """
    Aguarda o Gemini terminar de gerar a resposta via polling.
    Retorna quando o texto fica estável por `stable_cycles` ciclos consecutivos.
    """
    last = ""
    stable = 0
    start = time.time()

    while time.time() - start < max_wait:
        time.sleep(RESPONSE_POLL)
        current = get_response_text(page, prefer_code_blocks=prefer_code_blocks)

        if current and current == last:
            stable += 1
            if stable >= stable_cycles and not is_generating(page):
                return current
        else:
            stable = 0
            last = current

        if is_generating(page):
            stable = 0

    return last or ""


def wait_for_ack(page, timeout: int = 30) -> str:
    """Aguarda confirmação curta do Gemini (ex: 'OK') entre turnos."""
    return wait_for_response(page, max_wait=timeout, stable_cycles=2)


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Divide o texto em blocos de até `size` chars, quebrando em parágrafos."""
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", " "):
                pos = text.rfind(sep, start, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def apply_vars(text: str, vars_list: list[str] | None) -> str:
    """Substitui {chave} no texto pelos valores de --var chave=valor."""
    if not vars_list:
        return text
    for entry in vars_list:
        if "=" not in entry:
            print(f"Aviso: --var '{entry}' ignorado (esperado chave=valor)", file=sys.stderr)
            continue
        key, _, value = entry.partition("=")
        text = text.replace(f"{{{key.strip()}}}", value.strip())
    return text


def send_multiturn(
    page,
    chunks: list[str],
    trigger_word: str,
    ack_timeout: int = 45,
    prefer_code_blocks: bool = False,
) -> str:
    """
    Envia conteúdo dividido em múltiplos turnos:
      Turno 0  — instrução de espera
      Turno 1..N — partes do conteúdo
      Turno N+1 — trigger_word dispara a geração da resposta final

    Args:
        trigger_word: Palavra enviada no turno final para disparar a resposta
                      (ex: 'ANALISAR' para JSON, 'GERAR' para código Python)
        prefer_code_blocks: Passado para wait_for_response no turno final.
    """
    n = len(chunks)
    print(
        f"[RPA] Multi-turno: {n} parte(s) de ~{CHUNK_SIZE:,} chars. "
        f"Trigger: '{trigger_word}'",
        file=sys.stderr,
    )

    # Turno 0: instrução
    intro = (
        f"Vou te enviar conteúdo dividido em {n} parte(s). "
        "Leia cada parte sem responder. "
        f"Só responda quando eu enviar '{trigger_word}'. "
        "Confirme com apenas 'OK'."
    )
    focus_input(page)
    inject_text(page, intro)
    send_message(page)
    wait_for_ack(page, timeout=30)

    # Turnos 1..N: partes
    for i, chunk in enumerate(chunks, 1):
        msg = f"PARTE {i}/{n}:\n\n{chunk}"
        if i == n:
            msg += "\n\n[FIM DO CONTEÚDO]"
        msg += "\n\nConfirme com 'OK'."
        print(f"[RPA] Enviando parte {i}/{n} ({len(chunk):,} chars)...", file=sys.stderr)
        focus_input(page)
        inject_text(page, msg)
        send_message(page)
        wait_for_ack(page, timeout=ack_timeout)

    # Turno final: trigger
    print(f"[RPA] Enviando '{trigger_word}' — aguardando resposta...", file=sys.stderr)
    focus_input(page)
    inject_text(page, trigger_word)
    send_message(page)

    return wait_for_response(page, prefer_code_blocks=prefer_code_blocks)
