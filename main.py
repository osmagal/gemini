"""
main.py — Ponto de entrada unificado para os módulos Gemini RPA.

Subcomandos:
  chat  Envia uma mensagem e retorna a resposta do Gemini como texto.
  pdf   Extrai dados de um PDF e retorna JSON estruturado.
  code  Gera código Python Playwright a partir de HTML + JSON + prompt.

Exemplos:
  python3 main.py chat --message "Resuma o que é machine learning em 3 linhas"

  python3 main.py pdf \\
      --pdf boleto_ficticio.pdf \\
      --prompt-file prompt.txt \\
      --output resultado.json

  python3 main.py code \\
      --html-file formulario.html \\
      --json-file dados.json \\
      --prompt "Preencha o formulário e clique em Enviar" \\
      --output script_gerado.py \\ 
      --execute
"""

import argparse
import json
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(
        f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ é necessário. "
        f"Versão atual: {sys.version_info.major}.{sys.version_info.minor}."
    )

import gemini
import gemini_chat
import gemini_code_python


# ---------------------------------------------------------------------------
# Subcomando: chat
# ---------------------------------------------------------------------------

def cmd_chat(args: argparse.Namespace) -> int:
    """Envia uma mensagem ao Gemini e imprime/salva a resposta."""
    if args.message:
        message = args.message
    elif args.message_file:
        mf = Path(args.message_file)
        if not mf.exists():
            print(f"Erro: arquivo não encontrado: {args.message_file}", file=sys.stderr)
            return 1
        message = mf.read_text(encoding="utf-8").strip()
    else:
        print("Erro: informe --message ou --message-file.", file=sys.stderr)
        return 1

    try:
        response = gemini_chat.chat(
            message=message,
            vars_list=args.var,
            show_browser=args.show_browser,
        )
    except RuntimeError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(response, encoding="utf-8")
        print(f"Resposta salva em: {args.output}", file=sys.stderr)
    else:
        print(response)

    return 0


# ---------------------------------------------------------------------------
# Subcomando: pdf
# ---------------------------------------------------------------------------

def cmd_pdf(args: argparse.Namespace) -> int:
    """Extrai dados de um PDF via Gemini e imprime/salva o JSON resultante."""

    # Resolve prompt
    if args.prompt:
        user_prompt = args.prompt
    elif args.prompt_file:
        pf = Path(args.prompt_file)
        if not pf.exists():
            print(f"Erro: arquivo de prompt não encontrado: {args.prompt_file}", file=sys.stderr)
            return 1
        user_prompt = pf.read_text(encoding="utf-8").strip()
    else:
        print("Erro: informe --prompt ou --prompt-file.", file=sys.stderr)
        return 1

    try:
        result = gemini.extract_from_pdf(
            pdf_path=args.pdf,
            user_prompt=user_prompt,
            vars_list=args.var,
            show_browser=args.show_browser,
        )
    except FileNotFoundError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1

    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Resultado salvo em: {args.output}", file=sys.stderr)
    else:
        print(output_json)

    return 0


# ---------------------------------------------------------------------------
# Subcomando: code
# ---------------------------------------------------------------------------

def cmd_code(args: argparse.Namespace) -> int:
    """Gera código Python Playwright via Gemini a partir de HTML + JSON + prompt."""

    # Resolve HTML
    if args.html:
        html_content = args.html
    else:
        hp = Path(args.html_file)
        if not hp.exists():
            print(f"Erro: arquivo HTML não encontrado: {args.html_file}", file=sys.stderr)
            return 1
        html_content = hp.read_text(encoding="utf-8")

    # Resolve JSON
    if args.json:
        raw_json = args.json
    else:
        jp = Path(args.json_file)
        if not jp.exists():
            print(f"Erro: arquivo JSON não encontrado: {args.json_file}", file=sys.stderr)
            return 1
        raw_json = jp.read_text(encoding="utf-8")

    try:
        json_data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        print(f"Erro: JSON inválido — {e}", file=sys.stderr)
        return 1

    # Resolve prompt
    if args.prompt:
        user_prompt = args.prompt
    else:
        pp = Path(args.prompt_file)
        if not pp.exists():
            print(f"Erro: arquivo de prompt não encontrado: {args.prompt_file}", file=sys.stderr)
            return 1
        user_prompt = pp.read_text(encoding="utf-8").strip()

    if args.execute and not args.output:
        print(
            "Erro: --execute requer --output para salvar o arquivo antes de executar.",
            file=sys.stderr,
        )
        return 1

    try:
        python_code = gemini_code_python.generate_code(
            html_content=html_content,
            json_data=json_data,
            user_prompt=user_prompt,
            vars_list=args.var,
            show_browser=args.show_browser,
            output_file=args.output,
            execute=args.execute,
        )
    except (RuntimeError, ValueError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1

    if not args.output:
        print(python_code)

    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Gemini RPA — extração de PDF e geração de código Python via IA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── Subcomando: chat ─────────────────────────────────────────────────────
    p_chat = sub.add_parser(
        "chat",
        help="Envia uma mensagem e retorna a resposta do Gemini como texto.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    msg_grp = p_chat.add_mutually_exclusive_group(required=True)
    msg_grp.add_argument("--message", "-m", metavar="TEXTO", help="Mensagem a enviar.")
    msg_grp.add_argument("--message-file", metavar="ARQUIVO", help="Arquivo .txt com a mensagem.")
    p_chat.add_argument(
        "--var",
        action="append",
        metavar="CHAVE=VALOR",
        help="Substitui {chave} na mensagem. Repetível.",
    )
    p_chat.add_argument("--output", metavar="ARQUIVO", help="Arquivo de saída (padrão: stdout).")
    p_chat.add_argument(
        "--show-browser",
        action="store_true",
        default=False,
        help="Exibe o navegador durante a execução.",
    )
    p_chat.set_defaults(func=cmd_chat)

    # ── Subcomando: pdf ──────────────────────────────────────────────────────
    p_pdf = sub.add_parser(
        "pdf",
        help="Extrai dados de um PDF e retorna JSON estruturado.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_pdf.add_argument(
        "--pdf", required=True, metavar="ARQUIVO", help="Caminho para o arquivo PDF."
    )
    pdf_prompt = p_pdf.add_mutually_exclusive_group(required=True)
    pdf_prompt.add_argument("--prompt", metavar="TEXTO", help="Prompt de extração (texto direto).")
    pdf_prompt.add_argument("--prompt-file", metavar="ARQUIVO", help="Arquivo .txt com o prompt.")
    p_pdf.add_argument(
        "--var",
        action="append",
        metavar="CHAVE=VALOR",
        help="Substitui {chave} no prompt. Repetível. Ex: --var data_atual=15/04/2026",
    )
    p_pdf.add_argument("--output", metavar="ARQUIVO", help="Arquivo JSON de saída (padrão: stdout).")
    p_pdf.add_argument(
        "--show-browser",
        action="store_true",
        default=False,
        help="Exibe o navegador durante a execução.",
    )
    p_pdf.set_defaults(func=cmd_pdf)

    # ── Subcomando: code ─────────────────────────────────────────────────────
    p_code = sub.add_parser(
        "code",
        help="Gera código Python Playwright a partir de HTML + JSON + prompt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    html_grp = p_code.add_mutually_exclusive_group(required=True)
    html_grp.add_argument("--html", metavar="HTML", help="Código HTML (string direta).")
    html_grp.add_argument("--html-file", metavar="ARQUIVO", help="Arquivo .html com o código.")

    json_grp = p_code.add_mutually_exclusive_group(required=True)
    json_grp.add_argument("--json", metavar="JSON", help="Dados JSON (string direta).")
    json_grp.add_argument("--json-file", metavar="ARQUIVO", help="Arquivo .json com os dados.")

    code_prompt = p_code.add_mutually_exclusive_group(required=True)
    code_prompt.add_argument("--prompt", metavar="TEXTO", help="Instruções de automação.")
    code_prompt.add_argument("--prompt-file", metavar="ARQUIVO", help="Arquivo .txt com o prompt.")

    p_code.add_argument(
        "--var",
        action="append",
        metavar="CHAVE=VALOR",
        help="Substitui {chave} no prompt. Repetível.",
    )
    p_code.add_argument("--output", metavar="ARQUIVO", help="Arquivo .py de saída (padrão: stdout).")
    p_code.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Executa o script gerado após salvar (requer --output).",
    )
    p_code.add_argument(
        "--show-browser",
        action="store_true",
        default=False,
        help="Exibe o navegador durante a execução.",
    )
    p_code.set_defaults(func=cmd_code)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
