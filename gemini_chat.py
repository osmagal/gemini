"""
gemini_chat.py — Módulo de chat simples com o Gemini.

API pública:
    chat(message) -> str

Envia uma mensagem de texto ao Gemini e retorna a resposta como string.
"""

import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from gemini_shared import (
    GEMINI_URL,
    DEFAULT_TIMEOUT,
    create_browser_context,
    wait_for_input,
    focus_input,
    inject_text,
    send_message,
    wait_for_response,
    apply_vars,
)


def chat(
    message: str,
    vars_list: list[str] | None = None,
    show_browser: bool = False,
) -> str:
    """
    Envia uma mensagem ao Gemini e retorna a resposta como string.

    Args:
        message:      Texto da mensagem a enviar.
        vars_list:    Substituições no formato ["chave=valor", ...].
        show_browser: Se True, exibe o navegador durante a execução.

    Returns:
        Resposta do Gemini como string.

    Raises:
        RuntimeError: Se houver falha na comunicação com o Gemini.
    """
    text = apply_vars(message, vars_list)

    with sync_playwright() as p:
        ctx = create_browser_context(p, headless=not show_browser)
        page = ctx.new_page()
        try:
            print("[RPA] Abrindo Gemini...", file=sys.stderr)
            page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            wait_for_input(page)

            print(f"[RPA] Enviando mensagem ({len(text):,} chars)...", file=sys.stderr)
            focus_input(page)
            inject_text(page, text)
            send_message(page)

            print("[RPA] Aguardando resposta...", file=sys.stderr)
            return wait_for_response(page)

        except PlaywrightTimeout as e:
            raise RuntimeError(
                f"Timeout no Gemini. Verifique se está logado na conta Google.\n{e}"
            ) from e
        finally:
            ctx.close()
