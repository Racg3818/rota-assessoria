import os
from supabase import create_client, Client
from flask import session, current_app

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

    # Cliente administrativo (para operações que não precisam de auth)
    supabase_admin: Client = create_client(_url, _key)

def get_supabase_client():
    """
    NOVO SISTEMA: Retorna cliente Supabase autenticado baseado no sistema profiles.
    SEGURANÇA: Sempre verificar se usuário está autenticado via profiles.
    """
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
            # Sem token: RLS funcionará baseado na configuração
            current_app.logger.info("SUPABASE_CLIENT: Cliente criado sem token, RLS ativo para user_id: %s", user_id)

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

def get_current_user_profile():
    """
    NOVO: Retorna o profile completo do usuário atual da tabela profiles.
    Substitui as tentativas de acessar auth.users.
    """
    user = session.get("user", {})
    user_id = user.get("id") or user.get("supabase_user_id")

    if not user_id:
        return None

    try:
        if not supabase_admin:
            return None

        result = supabase_admin.table("profiles").select("*").eq("id", user_id).execute()

        if result.data:
            profile = result.data[0]
            current_app.logger.debug("PROFILE: Profile encontrado para user_id: %s", user_id)
            return profile
        else:
            current_app.logger.warning("PROFILE: Nenhum profile encontrado para user_id: %s", user_id)
            return None

    except Exception as e:
        current_app.logger.error("PROFILE: Erro ao buscar profile: %s", e)
        return None

def update_user_profile(user_id: str, updates: dict):
    """
    NOVO: Atualiza dados do profile do usuário.
    """
    try:
        if not supabase_admin:
            return False

        # Filtrar apenas campos permitidos
        allowed_fields = ['nome', 'codigo_xp']
        filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not filtered_updates:
            return False

        result = supabase_admin.table("profiles").update(filtered_updates).eq("id", user_id).execute()

        current_app.logger.info("PROFILE: Profile atualizado para user_id: %s, campos: %s",
                               user_id, list(filtered_updates.keys()))
        return True

    except Exception as e:
        current_app.logger.error("PROFILE: Erro ao atualizar profile: %s", e)
        return False

def list_all_profiles(limit: int = 100):
    """
    NOVO: Lista todos os profiles (para admins).
    Substitui tentativas de listar auth.users.
    """
    try:
        if not supabase_admin:
            return []

        result = supabase_admin.table("profiles").select("*").order("created_at", desc=True).limit(limit).execute()

        current_app.logger.info("PROFILES: %d profiles encontrados", len(result.data or []))
        return result.data or []

    except Exception as e:
        current_app.logger.error("PROFILES: Erro ao listar profiles: %s", e)
        return []

def get_profile_by_email(email: str):
    """
    NOVO: Busca profile por email.
    Útil para validações e login.
    """
    try:
        if not supabase_admin:
            return None

        result = supabase_admin.table("profiles").select("*").eq("email", email).execute()

        if result.data:
            current_app.logger.debug("PROFILE: Profile encontrado para email: %s", email)
            return result.data[0]
        else:
            current_app.logger.debug("PROFILE: Nenhum profile encontrado para email: %s", email)
            return None

    except Exception as e:
        current_app.logger.error("PROFILE: Erro ao buscar profile por email: %s", e)
        return None

# Mantém compatibilidade com código existente
supabase = supabase_admin