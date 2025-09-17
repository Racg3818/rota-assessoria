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
        # Para criação de usuários e login inicial, usar cliente admin e anon separadamente
        supabase_admin = None
        supabase_anon = None

        try:
            from supabase_client import supabase_admin as admin_client
            supabase_admin = admin_client
        except:
            pass

        try:
            from supabase import create_client
            import os
            _url = os.getenv("SUPABASE_URL")
            _anon_key = os.getenv("SUPABASE_ANON_KEY")
            current_app.logger.info("AUTH: URL: %s, ANON_KEY disponível: %s", bool(_url), bool(_anon_key))
            if _url and _anon_key:
                supabase_anon = create_client(_url, _anon_key)
                current_app.logger.info("AUTH: Cliente anônimo criado com sucesso")
            else:
                current_app.logger.error("AUTH: URL ou ANON_KEY faltando")
        except Exception as e:
            current_app.logger.error("AUTH: Erro ao criar cliente anônimo: %s", e)

        if supabase_admin and supabase_anon:
            user_id = None
            access_token = None
            refresh_token = None
            
            try:
                # 1) Tenta fazer login real com sign in with password (se existir)
                # Para isso, primeiro tentamos criar o usuário com senha padrão
                temp_password = f"temp_{codigo_xp}_{senha or 'default'}"
                
                try:
                    # Criar usuário com senha temporária usando cliente admin
                    created = supabase_admin.auth.admin.create_user({
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

                # 2) Fazer login real para obter tokens usando cliente anônimo
                try:
                    sign_in_result = supabase_anon.auth.sign_in_with_password({
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
                        # Listar todos e filtrar por email usando cliente admin
                        listed = supabase_admin.auth.admin.list_users()
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
                # SISTEMA AUTOMÁTICO DE MAPEAMENTO ESCALÁVEL
                try:
                    from supabase_client import supabase_admin

                    # 1. Buscar user_id existente em user_prefs (mapeamento direto)
                    prefs_result = supabase_admin.table('user_prefs').select('user_id').eq('user_key', email).limit(1).execute()
                    if prefs_result.data:
                        user_id = prefs_result.data[0]['user_id']
                        current_app.logger.info("AUTH: User ID encontrado em user_prefs: %s", user_id)
                    else:
                        # 2. Buscar por código XP em clientes existentes
                        current_app.logger.info("AUTH: Tentando mapear %s por código XP: %s", email, codigo_xp)

                        if codigo_xp:
                            clientes_result = supabase_admin.table('clientes').select('user_id').eq('codigo_xp', codigo_xp).limit(1).execute()
                            if clientes_result.data:
                                existing_user_id = clientes_result.data[0]['user_id']
                                current_app.logger.info("AUTH: Encontrado user_id por código XP %s: %s", codigo_xp, existing_user_id)

                                # 3. Criar mapeamento automático email -> user_id
                                try:
                                    # Inserir no formato correto para o schema
                                    insert_result = supabase_admin.table('user_prefs').insert({
                                        'user_key': email,
                                        'key': 'email_mapping',
                                        'value': email  # Supabase converte automaticamente para JSONB
                                    }).execute()

                                    # Atualizar user_id se trigger não definir automaticamente
                                    if insert_result.data:
                                        record_id = insert_result.data[0]['id']
                                        supabase_admin.table('user_prefs').update({
                                            'user_id': existing_user_id
                                        }).eq('id', record_id).execute()

                                    current_app.logger.info("AUTH: Mapeamento automático criado: %s -> %s", email, existing_user_id)
                                except Exception as mapping_error:
                                    current_app.logger.warning("AUTH: Erro ao criar mapeamento (pode já existir): %s", mapping_error)

                                user_id = existing_user_id
                            else:
                                current_app.logger.info("AUTH: Código XP %s não encontrado em clientes existentes", codigo_xp)

                        # 4. Fallback para usuários conhecidos hardcoded
                        if not user_id:
                            if email == 'renan.godinho@svninvest.com.br':
                                user_id = '49bfe132-04dc-4552-9088-99acea0f9310'
                                current_app.logger.info("AUTH: Usando user_id conhecido para Renan: %s", user_id)
                            else:
                                # 5. Criar novo user_id apenas se necessário
                                import hashlib
                                import uuid
                                email_hash = hashlib.sha256(email.encode()).digest()
                                user_id = str(uuid.UUID(bytes=email_hash[:16]))
                                current_app.logger.warning("AUTH: Criando NOVO user_id para %s: %s", email, user_id)

                                # Criar mapeamento para o novo usuário
                                try:
                                    # Inserir no formato correto para o schema
                                    insert_result = supabase_admin.table('user_prefs').insert({
                                        'user_key': email,
                                        'key': 'email_mapping',
                                        'value': email  # Supabase converte automaticamente para JSONB
                                    }).execute()

                                    # Atualizar user_id se trigger não definir automaticamente
                                    if insert_result.data:
                                        record_id = insert_result.data[0]['id']
                                        supabase_admin.table('user_prefs').update({
                                            'user_id': user_id
                                        }).eq('id', record_id).execute()

                                    current_app.logger.info("AUTH: Mapeamento criado para novo usuário: %s -> %s", email, user_id)
                                except Exception as new_mapping_error:
                                    current_app.logger.error("AUTH: Erro ao criar mapeamento para novo usuário: %s", new_mapping_error)

                except Exception as e:
                    current_app.logger.error("AUTH: Erro no sistema de mapeamento automático: %s", e)
                    # Fallback final
                    import hashlib
                    import uuid
                    email_hash = hashlib.sha256(email.encode()).digest()
                    user_id = str(uuid.UUID(bytes=email_hash[:16]))
                    current_app.logger.warning("AUTH: Fallback final UUID user_id=%s para %s", user_id, email)
                
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
        current_app.logger.warning("AUTH: Supabase não disponível ou falha na autenticação, usando fallback")

        # CORREÇÃO: Usar user_id conhecido para usuários existentes
        if email == 'renan.godinho@svninvest.com.br':
            fallback_id = '49bfe132-04dc-4552-9088-99acea0f9310'
            current_app.logger.info("AUTH: Fallback usando user_id conhecido para Renan: %s", fallback_id)
        elif email == 'daniel.alves@svninvest.com.br':
            fallback_id = 'ae346bfd-d168-4d9e-8c36-97939269d684'
            current_app.logger.info("AUTH: Fallback usando user_id conhecido para Daniel: %s", fallback_id)
        elif email == 'roberta.bonete@svninvest.com.br':
            fallback_id = 'f5dd2207-5769-466b-afdd-cc78e6e635f7'
            current_app.logger.info("AUTH: Fallback usando user_id conhecido para Roberta: %s", fallback_id)
        else:
            # Gera um UUID único baseado no email para novos usuários
            import hashlib
            import uuid
            # Gerar UUID determinístico baseado no email
            email_hash = hashlib.sha256(email.encode()).digest()
            fallback_id = str(uuid.UUID(bytes=email_hash[:16]))
            current_app.logger.info("AUTH: Fallback gerando novo user_id UUID para %s: %s", email, fallback_id)
        
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
