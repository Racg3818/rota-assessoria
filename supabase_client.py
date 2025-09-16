import os
from supabase import create_client, Client
from flask import session

_url = os.getenv("SUPABASE_URL")
_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
_anon_key = os.getenv("SUPABASE_ANON_KEY")

if not _url or not _key:
    raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configurados.")

# Log das configurações para debug (sem expor as chaves completas)
import logging
logging.info("SUPABASE_CONFIG: URL presente: %s", bool(_url))
logging.info("SUPABASE_CONFIG: SERVICE_ROLE_KEY presente: %s", bool(_key))
logging.info("SUPABASE_CONFIG: ANON_KEY presente: %s", bool(_anon_key))

# Debug: verificar conteúdo das chaves (primeiros/últimos caracteres)
if _anon_key:
    logging.info("SUPABASE_CONFIG: ANON_KEY prefix: %s...%s", _anon_key[:10], _anon_key[-10:])
if _key:
    logging.info("SUPABASE_CONFIG: SERVICE_KEY prefix: %s...%s", _key[:10], _key[-10:])

# Cliente administrativo (para operações que não precisam de auth)
supabase_admin: Client = create_client(_url, _key)

def get_supabase_client():
    """
    Retorna cliente Supabase configurado com token do usuário atual (se disponível).
    Fallback para cliente administrativo.
    """
    from flask import current_app
    
    user = session.get("user", {})
    access_token = user.get("access_token")
    
    current_app.logger.info("SUPABASE_CLIENT: Verificando sessão - user keys: %s", list(user.keys()))
    current_app.logger.info("SUPABASE_CLIENT: access_token presente: %s", bool(access_token))
    
    if access_token and _anon_key:
        try:
            # Cliente autenticado com token do usuário
            current_app.logger.info("SUPABASE_CLIENT: Criando cliente autenticado")
            client = create_client(_url, _anon_key)
            client.auth.set_session(access_token, user.get("refresh_token", ""))

            # Testar se o cliente está funcionando
            try:
                user_response = client.auth.get_user()
                current_app.logger.info("SUPABASE_CLIENT: Usuário autenticado: %s", user_response.user.id if user_response.user else "None")
                return client
            except Exception as e:
                current_app.logger.error("SUPABASE_CLIENT: Falha ao verificar usuário autenticado: %s", e)

        except Exception as e:
            current_app.logger.error("SUPABASE_CLIENT: Falha ao criar cliente autenticado: %s", e)
    elif access_token and not _anon_key:
        current_app.logger.warning("SUPABASE_CLIENT: Token de usuário presente mas SUPABASE_ANON_KEY não configurada")
    
    # Fallback: cliente administrativo
    current_app.logger.warning("SUPABASE_CLIENT: Usando cliente administrativo (fallback)")
    return supabase_admin

# Mantém compatibilidade com código existente
supabase = supabase_admin
