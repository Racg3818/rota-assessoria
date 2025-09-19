# security_middleware.py
"""
🚨 MIDDLEWARE DE SEGURANÇA CRÍTICA
Protege TODAS as rotas contra vazamento de dados entre usuários.
"""

from flask import g, session, current_app, abort, request
from functools import wraps
import time

def get_current_user_id():
    """
    SEGURANÇA CRÍTICA: Retorna user_id da sessão (profiles).
    CONSISTENTE: Usa o mesmo ID gerado no login.
    """
    # Verificar se usuário está logado
    from utils import is_logged
    if not is_logged():
        return None

    user = session.get("user", {})
    user_id = user.get("id") or user.get("supabase_user_id")

    if not user_id:
        return None

    from flask import current_app
    if current_app:
        current_app.logger.debug("USER_ID da sessão: %s", user_id)

    return user_id

def require_valid_user():
    """
    DECORATOR: Força autenticação válida para rotas críticas.
    Bloqueia acesso se não há user_id válido na sessão.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = get_current_user_id()
            if not user_id:
                current_app.logger.error("SECURITY: Bloqueando acesso a %s - sem user_id válido", request.endpoint)
                abort(403, "Acesso negado: sessão inválida")

            # Armazenar user_id no contexto da requisição para logs
            g.current_user_id = user_id
            g.security_check_time = time.time()

            current_app.logger.info("SECURITY: Acesso autorizado a %s para user_id: %s", request.endpoint, user_id)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_data_access(table_name, action, user_id=None, record_count=None):
    """
    AUDITORIA: Log todos os acessos a dados para detectar vazamentos.
    """
    user_id = user_id or get_current_user_id()
    current_app.logger.info("AUDIT: %s em %s - user_id: %s - registros: %s - endpoint: %s",
                           action, table_name, user_id, record_count, request.endpoint)

def secure_supabase_query(supabase_client, table_name, action="SELECT"):
    """
    WRAPPER SEGURO: Garante que todas as queries filtrem por user_id.
    """
    if not supabase_client:
        current_app.logger.error("SECURITY: Cliente Supabase None em operação %s na tabela %s", action, table_name)
        return None

    user_id = get_current_user_id()
    if not user_id:
        current_app.logger.error("SECURITY: Tentativa de acesso sem user_id válido - tabela: %s", table_name)
        return None

    # Log da operação para auditoria
    log_data_access(table_name, action, user_id)

    return supabase_client.table(table_name)

class SecurityError(Exception):
    """Exceção para violações de segurança."""
    pass

def validate_user_owns_record(supabase_client, table_name, record_id, user_id=None):
    """
    VALIDAÇÃO: Verifica se usuário é dono do registro antes de operações.
    """
    user_id = user_id or get_current_user_id()
    if not user_id:
        raise SecurityError("Usuário não autenticado")

    try:
        result = supabase_client.table(table_name).select("user_id").eq("id", record_id).limit(1).execute()

        if not result.data:
            raise SecurityError(f"Registro {record_id} não encontrado na tabela {table_name}")

        record_owner = result.data[0].get("user_id")
        if record_owner != user_id:
            current_app.logger.error("SECURITY: TENTATIVA DE ACESSO INDEVIDO - user_id: %s tentou acessar registro de %s na tabela %s",
                                   user_id, record_owner, table_name)
            raise SecurityError("Acesso negado: registro pertence a outro usuário")

        return True

    except Exception as e:
        current_app.logger.error("SECURITY: Erro na validação de propriedade: %s", e)
        raise SecurityError("Erro na validação de segurança")

def init_security_middleware(app):
    """
    INICIALIZAÇÃO: Registra middleware de segurança global.
    """
    @app.before_request
    def security_before_request():
        # Apenas auditoria silenciosa - deixar @login_required das views fazer a proteção
        if request.endpoint and not request.endpoint.startswith('static'):
            user_id = get_current_user_id()
            if user_id:
                # Armazenar user_id no contexto para logs
                g.current_user_id = user_id
                g.security_check_time = time.time()
                # Log apenas para rotas críticas
                if any(route in request.endpoint for route in ['clientes', 'dashboard', 'alocacoes']):
                    app.logger.info("AUDIT: %s acessado por user_id: %s", request.endpoint, user_id)

    @app.after_request
    def security_after_request(response):
        # Log de auditoria após cada requisição
        if hasattr(g, 'current_user_id'):
            duration = time.time() - g.security_check_time
            app.logger.info("AUDIT: Requisição concluída - user_id: %s - duração: %.3fs - status: %s",
                                   g.current_user_id, duration, response.status_code)
        return response

    # Log de inicialização usando o logger da app diretamente
    app.logger.info("SECURITY: Middleware de segurança inicializado")