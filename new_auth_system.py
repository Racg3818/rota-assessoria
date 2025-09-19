# ===============================================
# NOVO SISTEMA DE AUTENTICAÇÃO COM PROFILES
# ===============================================

from flask import Blueprint, render_template, request, redirect, url_for, session, current_app, flash
from utils import is_logged
import re
import uuid
import hashlib

# Imports do Supabase
try:
    from supabase_client import get_supabase_client, supabase_admin
except Exception:
    def get_supabase_client():
        return None
    supabase_admin = None

new_auth_bp = Blueprint('new_auth', __name__)

# ---------------- Helpers ----------------

def only_digits(s: str) -> str:
    return "".join(re.findall(r"\d+", s or ""))

def generate_deterministic_uuid(email: str, codigo_xp: str) -> str:
    """
    Gera UUID determinístico baseado em email + codigo_xp
    Garante que o mesmo usuário sempre tenha o mesmo ID
    """
    # Criar hash consistente
    content = f"{email.lower()}{codigo_xp}"
    hash_bytes = hashlib.sha256(content.encode()).digest()

    # Converter para UUID formato válido
    uuid_hex = hash_bytes[:16].hex()
    formatted_uuid = f"{uuid_hex[:8]}-{uuid_hex[8:12]}-{uuid_hex[12:16]}-{uuid_hex[16:20]}-{uuid_hex[20:32]}"

    return formatted_uuid

# ---------------- Routes ----------------

@new_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Já logado -> vai para o dashboard
    if request.method == 'GET' and is_logged():
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        # Limpar sessão anterior
        old_user = session.get('user', {})
        current_app.logger.info("AUTH: LOGOUT - Limpando sessão anterior: email=%s, user_id=%s",
                               old_user.get('email'), old_user.get('id'))
        session.clear()

        nome = (request.form.get('nome') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        codigo_xp = only_digits(request.form.get('codigo_xp') or '')
        senha = (request.form.get('senha') or '').strip()
        allowed = current_app.config.get('ALLOWED_DOMAIN', 'svninvest.com.br').lower()

        # Validações básicas
        if not nome:
            flash('Informe seu nome.', 'error')
            return render_template('login.html')

        current_app.logger.info("AUTH: Dados do formulário - nome: '%s', email: '%s', codigo_xp: '%s'",
                               nome, email, codigo_xp)

        if '@' not in email or not email.endswith('@' + allowed):
            flash(f'Use um e-mail @{allowed}.', 'error')
            return render_template('login.html')

        if not codigo_xp:
            flash('Informe seu código XP.', 'error')
            return render_template('login.html')

        # === NOVO SISTEMA COM PROFILES ===
        try:
            if not supabase_admin:
                flash('Sistema de autenticação indisponível. Tente novamente.', 'error')
                return render_template('login.html')

            # 1. Verificar se usuário já existe na tabela profiles
            existing_profile = supabase_admin.table("profiles").select("*").eq("email", email).execute()

            user_id = None
            access_token = None

            if existing_profile.data:
                # Usuário já existe - fazer login
                profile = existing_profile.data[0]
                user_id = profile['id']
                current_app.logger.info("AUTH: Usuário existente encontrado: %s", user_id)

                # Tentar fazer login com Supabase Auth
                try:
                    # Usar senha baseada no código XP
                    temp_password = f"xp_{codigo_xp}_pwd"

                    # Criar cliente anônimo para login
                    from supabase import create_client
                    supabase_anon = create_client(
                        current_app.config.get("SUPABASE_URL"),
                        current_app.config.get("SUPABASE_ANON_KEY")
                    )

                    sign_in_result = supabase_anon.auth.sign_in_with_password({
                        "email": email,
                        "password": temp_password
                    })

                    if hasattr(sign_in_result, 'session') and sign_in_result.session:
                        access_token = sign_in_result.session.access_token
                        current_app.logger.info("AUTH: Login com token realizado com sucesso")

                except Exception as e:
                    current_app.logger.warning("AUTH: Login com token falhou, usando sessão simples: %s", e)

            else:
                # Usuário novo - criar tanto no auth.users quanto no profiles
                try:
                    # Gerar UUID determinístico
                    user_id = generate_deterministic_uuid(email, codigo_xp)

                    # Criar usuário no Supabase Auth
                    temp_password = f"xp_{codigo_xp}_pwd"

                    created = supabase_admin.auth.admin.create_user({
                        "id": user_id,  # Usar UUID determinístico
                        "email": email,
                        "password": temp_password,
                        "email_confirm": True,
                        "user_metadata": {
                            "nome": nome,
                            "codigo_xp": codigo_xp
                        }
                    })

                    current_app.logger.info("AUTH: Usuário criado no auth.users: %s", user_id)

                    # O trigger irá criar automaticamente o profile
                    # Mas vamos verificar se foi criado
                    import time
                    time.sleep(0.5)  # Dar tempo para o trigger executar

                    profile_check = supabase_admin.table("profiles").select("*").eq("id", user_id).execute()
                    if not profile_check.data:
                        # Criar manualmente se o trigger falhou
                        supabase_admin.table("profiles").insert({
                            "id": user_id,
                            "nome": nome,
                            "email": email,
                            "codigo_xp": codigo_xp
                        }).execute()
                        current_app.logger.info("AUTH: Profile criado manualmente: %s", user_id)

                except Exception as e:
                    current_app.logger.error("AUTH: Falha ao criar usuário: %s", e)

                    # Se falha na criação, tentar buscar se já existe
                    retry_profile = supabase_admin.table("profiles").select("*").eq("email", email).execute()
                    if retry_profile.data:
                        user_id = retry_profile.data[0]['id']
                        current_app.logger.info("AUTH: Usuário encontrado após falha de criação: %s", user_id)
                    else:
                        flash('Erro ao criar conta. Tente novamente.', 'error')
                        return render_template('login.html')

            # 2. Criar sessão segura
            if user_id:
                session['user'] = {
                    'id': user_id,
                    'supabase_user_id': user_id,  # Compatibilidade
                    'nome': nome,
                    'email': email,
                    'codigo_xp': codigo_xp,
                    'access_token': access_token
                }

                current_app.logger.info("AUTH: LOGIN SUCESSO - user_id: %s, email: %s", user_id, email)
                flash(f'Bem-vindo, {nome}!', 'success')
                return redirect(url_for('dashboard.index'))
            else:
                flash('Erro interno. Tente novamente.', 'error')
                return render_template('login.html')

        except Exception as e:
            current_app.logger.error("AUTH: Erro geral no login: %s", e)
            flash('Erro no sistema de autenticação. Tente novamente.', 'error')
            return render_template('login.html')

    # GET request
    return render_template('login.html')

@new_auth_bp.route('/logout')
def logout():
    user = session.get('user', {})
    current_app.logger.info("AUTH: LOGOUT - user_id: %s, email: %s",
                           user.get('id'), user.get('email'))
    session.clear()
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('new_auth.login'))

# ===============================================
# HELPERS PARA MIGRAÇÃO
# ===============================================

def get_profile_by_email(email: str):
    """Busca profile por email"""
    try:
        if not supabase_admin:
            return None
        result = supabase_admin.table("profiles").select("*").eq("email", email).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        current_app.logger.error("Erro ao buscar profile: %s", e)
        return None

def get_profile_by_id(user_id: str):
    """Busca profile por ID"""
    try:
        if not supabase_admin:
            return None
        result = supabase_admin.table("profiles").select("*").eq("id", user_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        current_app.logger.error("Erro ao buscar profile: %s", e)
        return None

def update_profile(user_id: str, data: dict):
    """Atualiza dados do profile"""
    try:
        if not supabase_admin:
            return False
        supabase_admin.table("profiles").update(data).eq("id", user_id).execute()
        return True
    except Exception as e:
        current_app.logger.error("Erro ao atualizar profile: %s", e)
        return False