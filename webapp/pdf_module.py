import os
import tempfile
import time
from flask import Blueprint, render_template, request, flash
from werkzeug.utils import secure_filename

import gemini

ALLOWED_EXTENSIONS = {"pdf"}

pdf_bp = Blueprint("pdf", __name__, template_folder="templates")


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@pdf_bp.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    prompt = ""
    if request.method == "POST":
        prompt = request.form.get("prompt", "").strip()
        file = request.files.get("pdf_file")

        if not file or file.filename == "":
            error = "Envie um arquivo PDF para análise."
        elif not allowed_file(file.filename):
            error = "Apenas arquivos PDF são aceitos."
        elif not prompt:
            error = "Informe as instruções de análise do documento."
        else:
            filename = secure_filename(file.filename)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                file.save(tmp.name)
                temp_path = tmp.name

            try:
                start = time.time()
                extracted = gemini.extract_from_pdf(
                    pdf_path=temp_path,
                    user_prompt=prompt,
                    show_browser=False,
                )
                elapsed = time.time() - start
                result = extracted
                flash(f"Documento analisado em {elapsed:.1f} segundos.", "success")
            except Exception as exc:
                error = str(exc)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
    return render_template(
        "pdf.html",
        title="Análise de Documentos",
        result=result,
        prompt=prompt,
        error=error,
    )
