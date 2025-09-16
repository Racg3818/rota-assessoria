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

# Debug: verificar conteúdo das chaves (primeiros/últimos caracteres) com segurança
if _anon_key and len(_anon_key) > 20:
    logging.info("SUPABASE_CONFIG: ANON_KEY prefix: %s...%s", _anon_key[:10], _anon_key[-10:])
elif _anon_key:
    logging.warning("SUPABASE_CONFIG: ANON_KEY muito curta: %d chars", len(_anon_key))

if _key and len(_key) > 20:
    logging.info("SUPABASE_CONFIG: SERVICE_KEY prefix: %s...%s", _key[:10], _key[-10:])
elif _key:
    logging.warning("SUPABASE_CONFIG: SERVICE_KEY muito curta: %d chars", len(_key))

# Validação adicional de chaves JWT
if _anon_key and not _anon_key.startswith("eyJ"):
    logging.error("SUPABASE_CONFIG: ANON_KEY não parece ser um JWT válido")
if _key and not _key.startswith("eyJ"):
    logging.error("SUPABASE_CONFIG: SERVICE_KEY não parece ser um JWT válido")

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

    # Log apenas se necessário para reduzir spam
    if not access_token:
        current_app.logger.info("SUPABASE_CLIENT: Sem access_token, usando cliente admin")
        return supabase_admin

    if not _anon_key:
        current_app.logger.warning("SUPABASE_CLIENT: ANON_KEY não configurada, usando cliente admin")
        return supabase_admin

    try:
        # Cliente autenticado com token do usuário
        client = create_client(_url, _anon_key)

        # Definir headers de autorização
        client.postgrest.auth(_anon_key)
        client.rest.headers = {
            **client.rest.headers,
            "Authorization": f"Bearer {access_token}"
        }

        current_app.logger.info("SUPABASE_CLIENT: Cliente autenticado criado com token")
        return client

    except Exception as e:
        current_app.logger.error("SUPABASE_CLIENT: Falha ao criar cliente autenticado: %s", e)

    # Fallback: cliente administrativo
    current_app.logger.info("SUPABASE_CLIENT: Usando cliente administrativo (fallback)")
    return supabase_admin

# Mantém compatibilidade com código existente
supabase = supabase_admin
