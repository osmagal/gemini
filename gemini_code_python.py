"""
gemini_code_python.py — Módulo de geração de código Python Playwright via Gemini.

API pública:
    generate_code(html_content, json_data, user_prompt, url, vars_list, show_browser) -> str

O Gemini analisa o HTML, os dados JSON e o prompt, e retorna um script Python
executável que preenche campos e realiza as ações solicitadas.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

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
# Instrução de sistema
# ---------------------------------------------------------------------------
CODE_SYSTEM_INSTRUCTION = """\
Você é um especialista em automação web com Python e Playwright.
Sua tarefa é gerar um script Python que automatize as ações descritas sobre uma página já carregada.

CONTEXTO DE USO:
A aplicação que chamará este script já possui uma instância do Playwright e uma página (`page`)
aberta na URL correta. O código gerado NÃO deve abrir o navegador nem navegar para nenhuma URL.
O código deve apenas interagir com os elementos da página que já está carregada.

REGRAS OBRIGATÓRIAS — LEIA COM ATENÇÃO:
1. Retorne TODO o código em UM ÚNICO bloco de código markdown: ```python ... ```
2. NUNCA divida o código em múltiplos blocos. Um único bloco do início ao fim.
3. NÃO use page.goto(), NÃO abra navegador, NÃO crie contexto Playwright.
4. Gere uma função `run(page)` que recebe o objeto `page` já navegado como parâmetro.
5. Os dados do JSON devem estar definidos como variável `data` dentro de `run(page)`.
6. Use seletores robustos baseados na estrutura HTML fornecida (id, name, aria-label, CSS).
7. Adicione time.sleep() ou wait_for_*() adequados para garantir estabilidade.
8. Preencha os campos exatamente com os valores do JSON fornecido.
9. O bloco `if __name__ == "__main__":` deve existir apenas para teste local,
   abrindo o navegador e chamando `run(page)` — mas este bloco é secundário.

ESTRUTURA OBRIGATÓRIA DO SCRIPT:
```python
import time
from playwright.sync_api import Page, sync_playwright

def run(page: Page) -> None:
    data = { ... }  # dados do JSON aqui

    # interações com a página já carregada
    page.fill("#campo", data["campo"])
    page.click("#botao")

if __name__ == "__main__":
    # bloco de teste local — a aplicação principal NÃO usa este bloco
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("about:blank")  # substitua pela URL de teste
        run(page)
        input("Pressione Enter para fechar...")
        browser.close()
```
"""


# ---------------------------------------------------------------------------
# Extração e limpeza do código Python da resposta
# ---------------------------------------------------------------------------

def extract_python_code(text: str) -> str:
    """
    Extrai o código Python da resposta do Gemini.
    Remove fences markdown e corrige artefatos de renderização do browser
    (ex: __name__ → name quando tratado como negrito markdown).
    """
    # 1) Bloco ```python ... ``` ou ``` ... ```
    fence = re.search(r"```(?:python)?\s*\n?([\s\S]+?)\n?```", text, re.IGNORECASE)
    if fence:
        return _fix_artifacts(fence.group(1).strip())

    # 2) Texto que já começa com código Python
    stripped = text.strip()
    first = stripped.split("\n")[0].strip()
    if any(first.startswith(kw) for kw in ("import ", "from ", "#!", "#!/", "def ", "class ")):
        return _fix_artifacts(stripped)

    # 3) Busca o primeiro bloco que parece código
    match = re.search(r"((?:import |from |def |class |#!|#!/)[\s\S]+)", stripped)
    if match:
        return _fix_artifacts(match.group(1).strip())

    return _fix_artifacts(stripped)


def _fix_artifacts(code: str) -> str:
    """
    Corrige artefatos introduzidos pelo renderizador do Gemini:
    - `__name__` pode virar `name` (underscores interpretados como markdown bold)
    - `__main__` pode virar `main`
    """
    fixes = {
        r'\bif\s+name\s*==\s*["\']main["\']': 'if __name__ == "__main__"',
        r'\bname\b(\s*==\s*["\'])main(["\'])': '__name__\\1__main__\\2',
        r'(?<![_\w])__name(?![_\w])': '__name__',
        r'(?<![_\w])name__(?![_\w])': '__name__',
        r'(?<![_\w])__main(?![_\w])': '__main__',
        r'(?<![_\w])main__(?![_\w])': '__main__',
        r'(?<![_\w])__init(?![_\w])': '__init__',
        r'(?<![_\w])init__(?![_\w])': '__init__',
    }
    for pattern, replacement in fixes.items():
        code = re.sub(pattern, replacement, code)
    return code


# ---------------------------------------------------------------------------
# Montagem do contexto
# ---------------------------------------------------------------------------

def build_context(
    html_content: str,
    json_data: dict | list,
    user_prompt: str,
) -> str:
    """Monta o contexto completo (instrução + prompt + HTML + JSON)."""
    json_str = json.dumps(json_data, ensure_ascii=False, indent=2)

    return (
        f"{CODE_SYSTEM_INSTRUCTION}\n"
        f"**INSTRUÇÕES DE AUTOMAÇÃO:**\n{user_prompt}\n\n"
        f"**ESTRUTURA HTML DA PÁGINA:**\n{html_content}\n\n"
        f"**DADOS JSON PARA PREENCHIMENTO:**\n{json_str}\n"
    )


# ---------------------------------------------------------------------------
# Envio para o Gemini
# ---------------------------------------------------------------------------

def _send_context(page, context: str) -> str:
    """Envia o contexto em turno único ou multi-turno conforme o tamanho."""
    if len(context) <= CHUNK_SIZE:
        print(f"[RPA] Envio único ({len(context):,} chars)...", file=sys.stderr)
        focus_input(page)
        inject_text(page, context)
        send_message(page)
        print("[RPA] Aguardando código Python gerado...", file=sys.stderr)
        return wait_for_response(page, prefer_code_blocks=True)

    # Multi-turno: envia o contexto em partes e dispara com "GERAR"
    chunks = chunk_text(context, CHUNK_SIZE)
    return send_multiturn(
        page,
        chunks,
        trigger_word="GERAR",
        prefer_code_blocks=True,
    )


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def run(
    html_content: str,
    json_data: dict | list,
    user_prompt: str,
    show_browser: bool = False,
) -> str:
    """
    Abre o Gemini, envia HTML + JSON + prompt e retorna o código Python bruto.
    """
    context = build_context(html_content, json_data, user_prompt)

    with sync_playwright() as p:
        ctx = create_browser_context(p, headless=not show_browser)
        page = ctx.new_page()
        try:
            print("[RPA] Abrindo Gemini...", file=sys.stderr)
            page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            wait_for_input(page)
            return _send_context(page, context)
        except PlaywrightTimeout as e:
            raise RuntimeError(
                f"Timeout no Gemini. Verifique se está logado na conta Google.\n{e}"
            ) from e
        finally:
            ctx.close()


def generate_code(
    html_content: str,
    json_data: dict | list,
    user_prompt: str,
    vars_list: list[str] | None = None,
    show_browser: bool = False,
    output_file: str | None = None,
    execute: bool = False,
) -> str:
    """
    Gera um script Python Playwright via Gemini.

    O código gerado expõe uma função `run(page)` que recebe um objeto `page`
    do Playwright já navegado para a página correta. Não abre navegador nem
    navega para URLs — a aplicação chamadora é responsável por isso.

    Args:
        html_content: Código HTML da página (usado para identificar os seletores).
        json_data:    Dados a preencher (dict ou list).
        user_prompt:  Instruções de automação.
        vars_list:    Substituições no prompt no formato ["chave=valor", ...].
        show_browser: Se True, exibe o navegador Gemini durante a execução.
        output_file:  Se informado, salva o código gerado neste arquivo .py.
        execute:      Se True (e output_file informado), executa o script gerado.

    Returns:
        String com o código Python gerado e limpo.

    Raises:
        RuntimeError: Se houver falha na comunicação com o Gemini.
        ValueError:   Se o Gemini não retornar código Python válido.
    """
    prompt = apply_vars(user_prompt, vars_list)

    print(
        f"[gemini_code] HTML: {len(html_content):,} chars | "
        f"JSON: {len(json.dumps(json_data)):,} chars | "
        f"Prompt: {len(prompt):,} chars",
        file=sys.stderr,
    )

    raw_response = run(html_content, json_data, prompt, show_browser=show_browser)
    python_code = extract_python_code(raw_response)

    if not python_code:
        raise ValueError(
            "O Gemini não retornou código Python válido.\n"
            f"Resposta bruta:\n{raw_response[:500]}"
        )

    if output_file:
        out = Path(output_file)
        out.write_text(python_code, encoding="utf-8")
        out.chmod(0o755)
        print(f"[gemini_code] Código salvo em: {output_file}", file=sys.stderr)

        if execute:
            print(f"[gemini_code] Executando {output_file}...", file=sys.stderr)
            result = subprocess.run([sys.executable, str(out)])
            if result.returncode != 0:
                raise RuntimeError(
                    f"Script gerado encerrou com código {result.returncode}."
                )

    return python_code
