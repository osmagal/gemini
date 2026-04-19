from flask import Flask, render_template

from .chat_module import chat_bp
from .pdf_module import pdf_bp


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = "change-me-for-production"
    app.json.ensure_ascii = False

    app.register_blueprint(chat_bp, url_prefix="/chat")
    app.register_blueprint(pdf_bp, url_prefix="/pdf")

    @app.route("/")
    def index():
        return render_template("index.html")

    return app
