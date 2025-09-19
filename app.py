from flask import Flask
from config import Config
from models import db
from cache_manager import init_cache
from views.auth import auth_bp
from views.dashboard import dash_bp
from views.receita import receita_bp
from views.clientes import clientes_bp
from views.importar import importar_bp
from views.finadvisor import fin_bp
from views.alocacoes import alocacoes_bp
# 🚨 SEGURANÇA CRÍTICA: Middleware de proteção contra vazamento de dados
from security_middleware import init_security_middleware

# Silencia o probe do Chrome/DevTools
from flask import Blueprint

wellknown_bp = Blueprint("wellknown", __name__)

@wellknown_bp.route("/.well-known/appspecific/com.chrome.devtools.json", methods=["GET"])
def _chrome_devtools_probe():
    # 204 No Content evita poluir o log
    return ("", 204)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # === Filtro de moeda BRL disponível em todos os templates ===
    def brl(value):
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            return "R$ 0,00"
        s = f"{v:,.2f}"                 # 12,345,678.90
        s = s.replace(",", "§").replace(".", ",").replace("§", ".")
        return f"R$ {s}"
    app.jinja_env.filters["brl"] = brl

    # DB
    db.init_app(app)
    with app.app_context():
        db.create_all()

    # Cache
    init_cache(app)

    # 🚨 SEGURANÇA CRÍTICA: Inicializar middleware de proteção
    init_security_middleware(app)

    # Blueprints
    app.register_blueprint(wellknown_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(receita_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(importar_bp)
    app.register_blueprint(fin_bp)
    app.register_blueprint(alocacoes_bp)

    # Rota raiz para redirecionamento
    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(app.config.get("PORT", 3001)), debug=True)
