# views/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, session, current_app, flash
from utils import is_logged
import re

# Tenta importar o Supabase; mantém fallback se indisponível
try:
    from supabase_client import get_supabase_client
except Exception:
    def get_supabase_client():
        return None

# Defina o Blueprint ANTES de usar decorators
auth_bp = Blueprint('auth', __name__)

# ---------------- Helpers ----------------

def only_digits(s: str) -> str:
    return "".join(re.findall(r"\d+", s or ""))

# ---------------- Routes ----------------

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Já logado -> vai para o dashboard
    if request.method == 'GET' and is_logged():
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        # zera a sessão antes de processar novo login
        old_user = session.get('user', {})
        current_app.logger.info("AUTH: LOGOUT - Limpando sessão anterior: email=%s, user_id=%s", 
                               old_user.get('email'), old_user.get('id'))
        session.clear()

        nome = (request.form.get('nome') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        codigo_xp = only_digits(request.form.get('codigo_xp') or '')
        senha = (request.form.get('senha') or '').strip()  # campo opcional; obrigatório apenas se XP=69922
        allowed = current_app.config.get('ALLOWED_DOMAIN', 'svninvest.com.br').lower()

        # validações básicas
        if not nome:
            flash('Informe seu nome.', 'error')
            return render_template('login.html')
        if '@' not in email or not email.endswith('@' + allowed):
            flash(f'Use um e-mail @{allowed}.', 'error')
            return render_template('login.html')
        if not codigo_xp:
            flash('Informe seu código XP (apenas dígitos).', 'error')
            return render_template('login.html')

        # Regra especial: admin (XP 69922) precisa de senha
        if codigo_xp == "69922":
            if senha != "Racg147526":
                flash("Senha incorreta para o administrador.", "error")
                return render_template("login.html")

        # ---------- Fluxo Supabase (opcional) ----------
        supabase = get_supabase_client()
        if supabase:
            user_id = None
            access_token = None
            refresh_token = None
            
            try:
                # 1) Tenta fazer login real com sign in with password (se existir)
                # Para isso, primeiro tentamos criar o usuário com senha padrão
                temp_password = f"temp_{codigo_xp}_{senha or 'default'}"
                
                try:
                    # Criar usuário com senha temporária
                    created = supabase.auth.admin.create_user({
                        "email": email,
                        "password": temp_password,
                        "email_confirm": True,
                        "user_metadata": {
                            "nome": nome,
                            "codigo_xp": codigo_xp
                        }
                    })
                    user_id = created.user.id if hasattr(created, "user") and created.user else None
                    current_app.logger.info("AUTH: Usuário criado com sucesso: %s", user_id)
                except Exception as e:
                    current_app.logger.info("AUTH: create_user falhou (usuário já existe?): %s", e)
                
                # 2) Fazer login real para obter tokens
                try:
                    sign_in_result = supabase.auth.sign_in_with_password({
                        "email": email,
                        "password": temp_password
                    })
                    if hasattr(sign_in_result, 'user') and sign_in_result.user:
                        user_id = sign_in_result.user.id
                        access_token = getattr(sign_in_result.session, 'access_token', None)
                        refresh_token = getattr(sign_in_result.session, 'refresh_token', None)
                        current_app.logger.info("AUTH: Login bem-sucedido com tokens")
                except Exception as e:
                    current_app.logger.warning("AUTH: sign_in_with_password falhou: %s", e)
                    # Fallback: localizar usuário por email (API corrigida)
                    try:
                        # CORREÇÃO: list_users() não aceita parâmetro email
                        # Listar todos e filtrar por email
                        listed = supabase.auth.admin.list_users()
                        users = getattr(listed, "data", {}).get("users", []) if hasattr(listed, "data") else []
                        matching_users = [u for u in users if u.get("email") == email]
                        
                        if matching_users:
                            user_id = matching_users[0]["id"]
                            current_app.logger.info("AUTH: Usuário encontrado por email: %s para %s", user_id, email)
                        else:
                            current_app.logger.warning("AUTH: Nenhum usuário encontrado para email: %s", email)
                    except Exception as e2:
                        current_app.logger.exception("AUTH: list/update user falhou (%s)", e2)

            except Exception as e:
                current_app.logger.exception("AUTH: Erro geral no fluxo Supabase: %s", e)

            # Garante que sempre temos um user_id válido
            if not user_id:
                import hashlib
                # FALLBACK ÚNICO: email + código XP + timestamp para garantir unicidade
                unique_string = f"{email}|{codigo_xp}|{nome}"
                user_id = hashlib.sha256(unique_string.encode()).hexdigest()[:32]
                current_app.logger.warning("AUTH: Supabase falhou, usando fallback user_id=%s para %s", user_id, email)
                
            # DEBUG: Log detalhado da sessão sendo criada
            session_data = {
                'id': user_id,
                'supabase_user_id': user_id,
                'nome': nome,
                'email': email,
                'codigo_xp': codigo_xp,
                'access_token': access_token,  # Token para autenticação
                'refresh_token': refresh_token,
                'raw_user_meta_data': {
                    "sub": user_id,
                    "email": email,
                    "codigo_xp": codigo_xp,
                    "email_verified": True,
                }
            }
            
            current_app.logger.info("AUTH: === CRIANDO NOVA SESSÃO ===")
            current_app.logger.info("AUTH: Email: %s", email)
            current_app.logger.info("AUTH: Nome: %s", nome)
            current_app.logger.info("AUTH: Código XP: %s", codigo_xp)
            current_app.logger.info("AUTH: User ID gerado: %s", user_id)
            current_app.logger.info("AUTH: Tem access_token: %s", bool(access_token))
            current_app.logger.info("AUTH: ================================")
            
            session['user'] = session_data
            return redirect(url_for('dashboard.index'))

        # ---------- Fallback sem Supabase ----------
        # Gera um ID único baseado no email para manter isolamento de dados
        import hashlib
        fallback_id = hashlib.sha256(email.encode()).hexdigest()[:32]
        
        session['user'] = {
            'id': fallback_id,
            'supabase_user_id': fallback_id,
            'nome': nome,
            'email': email,
            'codigo_xp': codigo_xp,
            'raw_user_meta_data': {
                "sub": fallback_id,
                "email": email,
                "codigo_xp": codigo_xp,
                "email_verified": True,
            }
        }
        return redirect(url_for('dashboard.index'))

    # GET
    return render_template('login.html')

@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
