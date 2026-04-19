import time
from flask import Blueprint, render_template, request, flash

import gemini_chat

chat_bp = Blueprint("chat", __name__, template_folder="templates")


@chat_bp.route("/", methods=["GET", "POST"])
def index():
    response = None
    error = None
    message = ""
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message:
            error = "Informe uma mensagem para enviar ao Gemini."
        else:
            try:
                start = time.time()
                response = gemini_chat.chat(message=message, show_browser=False)
                elapsed = time.time() - start
                flash(f"Resposta recebida em {elapsed:.1f} segundos.", "success")
            except Exception as exc:
                error = str(exc)
    return render_template(
        "chat.html",
        title="Chat Gemini",
        response=response,
        message=message,
        error=error,
    )
