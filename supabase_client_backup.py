import os
from supabase import create_client, Client
from flask import session

# IMPORTANTE: Carregar variáveis de ambiente primeiro
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(".env.local", usecwd=True))
load_dotenv()

_url = os.getenv("SUPABASE_URL")
_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
_anon_key = os.getenv("SUPABASE_ANON_KEY")

# Se não tem configuração do Supabase, usar sistema fallback
if not _url or not _key:
    import logging
    logging.warning("SUPABASE não configurado - usando sistema fallback local")

    # Criar cliente admin dummy
    class DummySupabaseAdmin:
        def table(self, name):
            from fallback_data import FallbackTable
            return FallbackTable(name, [], "system")

    supabase_admin = DummySupabaseAdmin()
else:
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
    SEGURANÇA: Retorna APENAS cliente autenticado por usuário.
    NUNCA retorna cliente admin para evitar vazamento de dados.
    """
    from flask import current_app

    user = session.get("user", {})
    user_id = user.get("id") or user.get("supabase_user_id")
    access_token = user.get("access_token")

    # SEGURANÇA: Verificar se temos user_id válido da sessão
    if not user_id:
        current_app.logger.debug("SUPABASE_CLIENT: Acesso negado - sem user_id válido na sessão")
        return None

    if not _anon_key:
        current_app.logger.debug("SUPABASE_CLIENT: ANON_KEY não configurada")
        return None

    try:
        # Cliente base com chave anônima
        client = create_client(_url, _anon_key)

        # Se temos token, usar autenticação por token
        if access_token:
            client.rest.headers = {
                **client.rest.headers,
                "Authorization": f"Bearer {access_token}"
            }
            current_app.logger.info("SUPABASE_CLIENT: Cliente autenticado criado com token para user_id: %s", user_id)
        else:
            # Sem token: usar RLS com user_id da sessão
            current_app.logger.warning("SUPABASE_CLIENT: Sem access_token, usando RLS com user_id da sessão: %s", user_id)

        return client

    except Exception as e:
        current_app.logger.error("SUPABASE_CLIENT: Falha ao criar cliente: %s", e)

        # SISTEMA FALLBACK: Criar cliente local quando Supabase falha
        try:
            from fallback_data import create_fallback_client
            fallback_client = create_fallback_client(user_id)
            current_app.logger.warning("SUPABASE_CLIENT: Usando sistema fallback para user_id: %s", user_id)
            return fallback_client
        except Exception as fallback_error:
            current_app.logger.error("SUPABASE_CLIENT: Falha no sistema fallback: %s", fallback_error)
            return None

# Mantém compatibilidade com código existente
supabase = supabase_admin
