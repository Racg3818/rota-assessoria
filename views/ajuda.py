from flask import Blueprint, render_template
from utils import login_required

ajuda_bp = Blueprint("ajuda", __name__, url_prefix="/ajuda")

@ajuda_bp.route("/", methods=["GET"])
@login_required
def index():
    """
    🆘 Tela de Ajuda - Instruções para download de arquivos
    """
    return render_template("ajuda/index.html")
