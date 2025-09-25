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

auth_bp = Blueprint('auth', __name__)

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

@auth_bp.route('/login', methods=['GET', 'POST'])
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
                # Usuário já existe - fazer login direto via profiles
                profile = existing_profile.data[0]
                user_id = profile['id']

                # Verificar se o código XP bate (autenticação simples)
                if profile.get('codigo_xp') == codigo_xp:
                    current_app.logger.info("AUTH: Login autorizado via profiles para user_id: %s", user_id)
                    access_token = None  # Usar SERVICE_ROLE sem token
                else:
                    current_app.logger.warning("AUTH: Código XP incorreto para %s", email)
                    flash('Código XP incorreto.', 'error')
                    return render_template('login.html')

            else:
                # Usuário novo - criar usuário auth.users + profile
                try:
                    # 1. Verificar se já existe profile órfão para este email
                    existing_orphan = supabase_admin.table("profiles").select("id").eq("email", email).execute()
                    if existing_orphan.data:
                        orphan_id = existing_orphan.data[0]["id"]
                        current_app.logger.warning("AUTH: Removendo profile órfão para %s: %s", email, orphan_id)

                        # Verificar se auth.user existe para este ID
                        try:
                            auth_check = supabase_admin.auth.admin.get_user_by_id(orphan_id)
                            if not auth_check.user:
                                # Profile órfão confirmado - deletar
                                supabase_admin.table("profiles").delete().eq("id", orphan_id).execute()
                                current_app.logger.info("AUTH: Profile órfão removido: %s", orphan_id)
                        except:
                            # auth.user não existe - deletar profile órfão
                            supabase_admin.table("profiles").delete().eq("id", orphan_id).execute()
                            current_app.logger.info("AUTH: Profile órfão removido: %s", orphan_id)

                    # 2. Criar usuário na tabela auth.users primeiro (Supabase gera o UUID)
                    auth_user = supabase_admin.auth.admin.create_user({
                        "email": email,
                        "email_confirm": True,
                        "user_metadata": {
                            "nome": nome,
                            "codigo_xp": codigo_xp
                        }
                    })

                    # 3. Usar o UUID real gerado pelo Supabase
                    user_id = auth_user.user.id

                    # 4. Verificar se profile já foi criado automaticamente (trigger)
                    # e atualizar ou criar conforme necessário
                    existing_profile = supabase_admin.table("profiles").select("*").eq("id", user_id).execute()

                    if existing_profile.data:
                        # Profile já existe (criado por trigger) - apenas atualizar os dados
                        supabase_admin.table("profiles").update({
                            "nome": nome,
                            "email": email,
                            "codigo_xp": codigo_xp
                        }).eq("id", user_id).execute()
                        current_app.logger.info("AUTH: Profile existente atualizado: %s", user_id)
                    else:
                        # Profile não existe - criar manualmente
                        supabase_admin.table("profiles").insert({
                            "id": user_id,
                            "nome": nome,
                            "email": email,
                            "codigo_xp": codigo_xp
                        }).execute()
                        current_app.logger.info("AUTH: Profile criado manualmente: %s", user_id)

                    current_app.logger.info("AUTH: Novo usuário e profile configurados: %s", user_id)
                    access_token = None  # Usar SERVICE_ROLE sem token

                except Exception as e:
                    current_app.logger.error("AUTH: Falha ao criar usuário/profile: %s", e)

                    # Tentar limpar dados parciais
                    try:
                        if 'user_id' in locals():
                            supabase_admin.auth.admin.delete_user(user_id)
                            supabase_admin.table("profiles").delete().eq("id", user_id).execute()
                            current_app.logger.info("AUTH: Cleanup realizado para user_id: %s", user_id)
                    except Exception as cleanup_error:
                        current_app.logger.warning("AUTH: Falha no cleanup: %s", cleanup_error)

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

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    user = session.get('user', {})
    current_app.logger.info("AUTH: LOGOUT - user_id: %s, email: %s",
                           user.get('id'), user.get('email'))
    session.clear()
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('auth.login'))

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