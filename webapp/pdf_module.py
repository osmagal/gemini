import os
import tempfile
import time
import uuid
import threading
from flask import Blueprint, render_template, request, jsonify, flash
from werkzeug.utils import secure_filename

import gemini

ALLOWED_EXTENSIONS = {"pdf"}

pdf_bp = Blueprint("pdf", __name__, template_folder="templates")

# Armazenamento em memória para progresso e resultados
tasks = {}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def run_analysis_task(task_id, temp_path, prompt):
    try:
        def progress_callback(msg, percent):
            tasks[task_id]["status"] = msg
            tasks[task_id]["percent"] = percent

        result = gemini.extract_from_pdf(
            pdf_path=temp_path,
            user_prompt=prompt,
            show_browser=False,
            progress_callback=progress_callback
        )
        tasks[task_id]["result"] = result
        tasks[task_id]["completed"] = True
    except Exception as exc:
        tasks[task_id]["error"] = str(exc)
        tasks[task_id]["completed"] = True
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

@pdf_bp.route("/", methods=["GET"])
def index():
    return render_template(
        "pdf.html",
        title="Análise de Documentos",
    )

@pdf_bp.route("/analyze", methods=["POST"])
def analyze():
    prompt = request.form.get("prompt", "").strip()
    file = request.files.get("pdf_file")

    if not file or file.filename == "":
        return jsonify({"error": "Envie um arquivo PDF para análise."}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Apenas arquivos PDF são aceitos."}), 400
    if not prompt:
        return jsonify({"error": "Informe as instruções de análise do documento."}), 400

    task_id = str(uuid.uuid4())
    
    # Salva arquivo temporário
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file.save(tmp.name)
        temp_path = tmp.name

    tasks[task_id] = {
        "status": "Iniciando...",
        "percent": 0,
        "completed": False,
        "result": None,
        "error": None
    }

    # Inicia thread
    thread = threading.Thread(target=run_analysis_task, args=(task_id, temp_path, prompt))
    thread.start()

    return jsonify({"task_id": task_id})

@pdf_bp.route("/status/<task_id>")
def status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Tarefa não encontrada"}), 404
    
    return jsonify({
        "status": task["status"],
        "percent": task["percent"],
        "completed": task["completed"],
        "error": task["error"]
    })

@pdf_bp.route("/result/<task_id>")
def result(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Tarefa não encontrada"}), 404
    
    if not task["completed"]:
        return jsonify({"error": "Tarefa ainda em processamento"}), 400
        
    return jsonify({"result": task["result"], "error": task["error"]})
