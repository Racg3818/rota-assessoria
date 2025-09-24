# views/admin.py
"""
📊 TELA ADMINISTRATIVA - VISÃO CONSOLIDADA
Acesso restrito apenas para renan.godinho@svninvest.com.br
Exibe métricas de todos os assessores em uma única tela.
CORRIGIDO: Usando tabela 'profiles' em vez de 'usuarios'
"""

from flask import Blueprint, render_template, current_app, session, abort
from datetime import datetime
from collections import defaultdict

try:
    from supabase_client import supabase, get_supabase_client
except Exception:
    supabase = None

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Email autorizado para acessar a tela administrativa
ADMIN_EMAIL = "renan.godinho@svninvest.com.br"

def _is_admin_user():
    """Verifica se o usuário atual tem permissão de admin"""
    user_session = session.get("user", {})
    user_email = user_session.get("email", "").strip().lower()
    return user_email == ADMIN_EMAIL.lower()

def _admin_required(f):
    """Decorator para rotas que requerem acesso de admin"""
    def decorated_function(*args, **kwargs):
        if not _is_admin_user():
            current_app.logger.warning(f"ADMIN_ACCESS_DENIED: User {session.get('user', {}).get('email', 'UNKNOWN')} tentou acessar área administrativa")
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def _to_float(value):
    """Converte valor para float de forma segura"""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Remove formatação brasileira se houver
        if isinstance(value, str):
            value = value.replace(".", "").replace(",", ".")
        return float(value)
    except (ValueError, TypeError):
        return 0.0

# Lista de usuários para monitorar
USUARIOS_MONITORADOS = [
    "vinicius.carvalho@svninvest.com.br",
    "roberta.bonete@svninvest.com.br",
    "matheus.campos@svninvest.com.br",
    "renato.kinji@svninvest.com.br",
    "daniel.alves@svninvest.com.br",
    "leonardo.baggio@svninvest.com.br",  # Corrigido o typo "svninvst"
    "renan.godinho@svninvest.com.br"
]

def _get_user_by_email(email):
    """Busca dados do usuário pelo email"""
    if not supabase:
        return None

    try:
        res = supabase.table("profiles").select("*").eq("email", email).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        current_app.logger.error(f"Erro buscando usuário {email}: {e}")
        return None

def _calculate_receita_escritorio_ativa(user_id):
    """EXATA função do Dashboard _receita_escritorio_mes_atual_via_alocacoes adaptada para admin"""
    if not supabase:
        return 0.0

    mes_atual = datetime.now().strftime("%Y-%m")
    total = 0.0

    try:
        q = supabase.table("alocacoes").select(
            "valor, created_at, efetivada, produto:produto_id ( roa_pct )"
        )
        q = q.eq("user_id", user_id)  # Filtrar por user_id específico
        res = q.execute()
        rows = list(res.data or [])
    except Exception as e:
        current_app.logger.info("admin: falha ao buscar alocacoes (%s)", e)
        rows = []

    for r in rows:
        # IMPORTANTE: Só considerar alocações EFETIVADAS
        efetivada = r.get("efetivada")
        if not efetivada:  # Se não efetivada, pular
            continue

        # Para receita ativa do mês, considerar alocações criadas OU efetivadas no mês atual
        created_month = (r.get("created_at") or "")[:7]

        if created_month != mes_atual:
            continue

        valor = _to_float(r.get("valor"))
        produto = r.get("produto") or {}
        roa_pct = _to_float(produto.get("roa_pct"))

        receita_item = valor * (roa_pct / 100.0)
        total += receita_item

    return total

def _calculate_receita_assessor_recorrente(user_id):
    """EXATA função do Dashboard _receita_assessor_recorrente adaptada para admin"""
    if not supabase:
        return 0.0

    import json

    try:
        # Buscar o último mês com dados na tabela
        res_meses = supabase.table("receita_itens").select(
            "data_ref"
        ).eq("user_id", user_id).order("data_ref", desc=True).limit(1).execute()

        if not res_meses.data:
            return 0.0

        ultimo_mes_disponivel = res_meses.data[0].get("data_ref", "")
        if not ultimo_mes_disponivel:
            return 0.0

        # Extrair YYYY-MM do último mês
        mes_target = ultimo_mes_disponivel[:7]  # YYYY-MM

        # Buscar email do usuário para as preferências
        user_data = supabase.table("profiles").select("email").eq("id", user_id).limit(1).execute()
        if not user_data.data:
            return 0.0

        user_email = user_data.data[0].get("email", "").strip().lower()

        # Buscar categorias salvas nas preferências do usuário
        res_prefs = supabase.table("user_prefs").select("value").eq(
            "user_key", user_email
        ).eq("key", "recorrencia_produtos").eq("user_id", user_id).limit(1).execute()

        # Fallback para buscar apenas por user_id se não encontrar com user_key
        if not res_prefs.data:
            res_prefs = supabase.table("user_prefs").select("value").eq(
                "user_id", user_id
            ).eq("key", "recorrencia_produtos").limit(1).execute()

        selected_set = set()
        if res_prefs.data:
            categorias_value = res_prefs.data[0].get("value")
            if isinstance(categorias_value, str):
                try:
                    categorias = json.loads(categorias_value)
                    selected_set = set(categorias)
                except:
                    pass
            elif isinstance(categorias_value, list):
                selected_set = set(categorias_value)

        # Buscar receitas do último mês disponível
        res_receitas = supabase.table("receita_itens").select(
            "valor_liquido, produto, familia"
        ).eq("user_id", user_id).like("data_ref", f"{mes_target}%").execute()

        total_passiva = 0.0

        # Função para verificar família administrativa (mesma do Dashboard)
        def _is_admin_family(fam):
            fam_lower = fam.lower()
            return any(x in fam_lower for x in ["admin", "corretagem", "custódia", "escritório"])

        for receita in res_receitas.data or []:
            produto = (receita.get("produto") or "").strip()
            familia = (receita.get("familia") or "").strip()
            val_liq = _to_float(receita.get("valor_liquido"))

            # Pular família administrativa
            if _is_admin_family(familia):
                continue

            # Lógica EXATA do Dashboard
            produto_presente = bool(produto)

            if not produto_presente:
                # Se não tem produto, conta como recorrente
                total_passiva += val_liq
            else:
                # Se tem produto, só conta se estiver nas categorias selecionadas
                if not selected_set or (produto in selected_set):
                    total_passiva += val_liq

        return total_passiva

    except Exception as e:
        current_app.logger.error(f"Erro calculando receita assessor recorrente para user_id {user_id}: {e}")
        return 0.0

def _calculate_receita_escritorio_recorrente(user_id, clientes):
    """EXATA função do Dashboard _receita_escritorio_recorrente"""
    receita_assessor_rec = _calculate_receita_assessor_recorrente(user_id)

    if receita_assessor_rec <= 0:
        return 0.0

    if not clientes:
        return 0.0

    # Calcular média ponderada (mesmo cálculo usado em _receita_assessor_mes)
    total_net = 0.0
    total_net_ponderado = 0.0

    for cliente in clientes:
        net_total = _to_float(cliente.get("net_total", 0))
        repasse = _to_float(cliente.get("repasse", 0))

        if net_total > 0:
            total_net += net_total
            if repasse > 0:
                contribution = net_total * repasse / 100.0
                total_net_ponderado += contribution

    if total_net == 0 or total_net_ponderado == 0:
        return 0.0

    # Fórmula inversa: Receita Escritório = Receita Assessor ÷ 80% ÷ Média Ponderada
    media_ponderada_repasse = total_net_ponderado / total_net
    receita_escritorio_rec = receita_assessor_rec / 0.80 / media_ponderada_repasse

    return receita_escritorio_rec

def _calculate_bonus_ativo(user_id, mes_atual):
    """EXATA função do Dashboard _carregar_bonus_ativo_mes adaptada para admin"""
    if not supabase or not user_id:
        return 0.0

    def _calcular_valor_liquido_bonus(valor_bonus, liquido_assessor):
        """Função auxiliar para calcular valor líquido do bônus"""
        if liquido_assessor:
            return valor_bonus
        else:
            return valor_bonus * 0.80

    total_bonus = 0.0

    try:
        # Tentar com colunas novas primeiro
        try:
            resp = supabase.table("bonus_missoes").select(
                "valor_bonus, liquido_assessor"
            ).eq("user_id", user_id).eq("mes", mes_atual).eq("ativo", True).execute()

            bonus_list = resp.data or []
            total_bonus = sum(
                _calcular_valor_liquido_bonus(
                    _to_float(b.get("valor_bonus", 0)),
                    b.get("liquido_assessor", True)
                )
                for b in bonus_list
            )
        except Exception:
            # Fallback para apenas valor_bonus (sem cálculo de IR)
            resp = supabase.table("bonus_missoes").select(
                "valor_bonus"
            ).eq("user_id", user_id).eq("mes", mes_atual).eq("ativo", True).execute()

            bonus_list = resp.data or []
            total_bonus = sum(_to_float(b.get("valor_bonus", 0)) for b in bonus_list)

    except Exception as e:
        current_app.logger.warning(f"Erro ao carregar bônus para user_id {user_id}: {e}")
        total_bonus = 0.0

    return total_bonus

def _calculate_receita_escritorio(user_id, clientes):
    """EXATA função do Dashboard _receita_escritorio_total_mes"""
    receita_ativa = _calculate_receita_escritorio_ativa(user_id)
    receita_recorrente = _calculate_receita_escritorio_recorrente(user_id, clientes)
    mes_atual = datetime.now().strftime("%Y-%m")
    bonus_ativo = _calculate_bonus_ativo(user_id, mes_atual)

    total = receita_ativa + receita_recorrente + bonus_ativo
    return total

def _calculate_receita_assessor(receita_escritorio, clientes, user_id):
    """EXATA função do Dashboard _receita_assessor_mes - INCLUI BÔNUS"""
    if not clientes or receita_escritorio <= 0:
        return 0.0

    total_net = 0.0
    total_net_ponderado = 0.0

    for cliente in clientes:
        net_total = _to_float(cliente.get("net_total", 0))
        repasse = _to_float(cliente.get("repasse", 0))

        if net_total > 0:
            total_net += net_total
            if repasse > 0:
                contribution = net_total * repasse / 100.0
                total_net_ponderado += contribution

    if total_net == 0 or total_net_ponderado == 0:
        return 0.0

    # Fórmula base: Receita Escritório × 80% × (Média Ponderada do NET × Repasse)
    media_ponderada_repasse = total_net_ponderado / total_net
    receita_assessor_base = receita_escritorio * 0.80 * media_ponderada_repasse

    # Adicionar bônus ativos do mês (MESMA LÓGICA DO DASHBOARD)
    mes_atual = datetime.now().strftime("%Y-%m")
    bonus_ativo = _calculate_bonus_ativo(user_id, mes_atual)
    receita_assessor = receita_assessor_base + bonus_ativo

    return receita_assessor

# Função já definida anteriormente - removendo duplicata

def _calculate_user_metrics(user_id, user_email):
    """Calcula todas as métricas para um usuário específico"""

    if not supabase or not user_id:
        current_app.logger.warning(f"❌ ADMIN_METRICS: Supabase ou user_id inválido para {user_email}")
        return {
            "email": user_email,
            "user_id": user_id,
            "name": "N/A",
            "penetracao_xp": 0.0,
            "penetracao_mb": 0.0,
            "penetracao_total": 0.0,
            "meta_mes": 0.0,
            "receita_escritorio": 0.0,
            "receita_assessor": 0.0,
            "atingimento_pct": 0.0,
            "error": "Dados indisponíveis"
        }

    mes_atual = datetime.now().strftime("%Y-%m")

    try:
        # Buscar clientes do usuário
        current_app.logger.info(f"📋 ADMIN_METRICS: Buscando clientes para user_id {user_id}")
        clientes_res = supabase.table("clientes").select(
            "id, nome, net_total, repasse"
        ).eq("user_id", user_id).execute()

        clientes = clientes_res.data or []

        clientes_validos = [c for c in clientes if _to_float(c.get("net_total", 0)) > 0]
        total_clientes = len(clientes_validos)

        if total_clientes == 0:
            penetracao_xp = 0.0
            penetracao_mb = 0.0
            penetracao_total = 0.0
            xp_count = 0
            mb_count = 0
            total_clientes_com_alocacao = 0
        else:
            # Buscar alocações do usuário com informações dos produtos (APENAS EFETIVADAS)
            alocacoes_res = supabase.table("alocacoes").select(
                "cliente_id, produto_id, valor, efetivada, produtos(classe, em_campanha)"
            ).eq("user_id", user_id).eq("efetivada", True).execute()

            alocacoes = alocacoes_res.data or []

            # NOVA LÓGICA: Organizar alocações por cliente para identificar tipos exclusivos
            from collections import defaultdict
            clientes_alocacoes = defaultdict(list)

            # Todos os clientes com qualquer alocação efetivada
            clientes_com_alocacao = set()

            for i, alocacao in enumerate(alocacoes):
                cliente_id = alocacao.get("cliente_id")
                produto = alocacao.get("produtos", {})
                classe = produto.get("classe", "")
                em_campanha = produto.get("em_campanha", False)
                efetivada = alocacao.get("efetivada", False)

                # Debug detalhado para as primeiras 3 alocações

                # Só considerar alocações efetivadas
                if efetivada:
                    clientes_com_alocacao.add(cliente_id)

                    is_mb = classe == "Renda Fixa Digital"
                    is_xp = classe != "Renda Fixa Digital" and em_campanha

                    clientes_alocacoes[cliente_id].append({
                        'is_mb': is_mb,
                        'is_xp': is_xp,
                        'classe': classe,
                        'em_campanha': em_campanha
                    })

            # REGRA CORRIGIDA:
            # XP = Clientes que têm QUALQUER alocação XP (exclusivo ou misto)
            # MB = Clientes que têm APENAS alocações MB (exclusivo)
            clientes_xp = set()
            clientes_apenas_mb = set()

            for cliente_id, alocacoes_cliente in clientes_alocacoes.items():
                has_mb = any(a['is_mb'] for a in alocacoes_cliente)
                has_xp = any(a['is_xp'] for a in alocacoes_cliente)

                if has_xp:
                    # Qualquer cliente com alocação XP conta para XP
                    clientes_xp.add(cliente_id)

                if has_mb and not has_xp:
                    # Apenas clientes que têm SOMENTE MB contam para MB
                    clientes_apenas_mb.add(cliente_id)

            xp_count = len(clientes_xp)
            mb_count = len(clientes_apenas_mb)
            total_clientes_com_alocacao = len(clientes_com_alocacao)


            # Debug sobre clientes mistos
            clientes_mistos = set()
            for cliente_id, alocacoes_cliente in clientes_alocacoes.items():
                has_mb = any(a['is_mb'] for a in alocacoes_cliente)
                has_xp = any(a['is_xp'] for a in alocacoes_cliente)
                if has_xp and has_mb:
                    clientes_mistos.add(cliente_id)


            # Cálculos corretos com NOVA REGRA:
            # - Penetração XP: % de clientes com QUALQUER alocação XP
            # - Penetração MB: % de clientes que APENAS têm alocações MB
            # - Penetração Total: Soma simples de XP + MB
            penetracao_xp = (xp_count / total_clientes * 100) if total_clientes > 0 else 0.0
            penetracao_mb = (mb_count / total_clientes * 100) if total_clientes > 0 else 0.0
            penetracao_total = penetracao_xp + penetracao_mb


        # Buscar meta do mês
        meta_res = supabase.table("metas_mensais").select("meta_receita").eq(
            "user_id", user_id
        ).eq("mes", mes_atual).limit(1).execute()

        meta_mes = _to_float(meta_res.data[0].get("meta_receita", 0)) if meta_res.data else 0.0

        # Calcular receita usando a mesma lógica do Dashboard

        # Receita Escritório: usando lógica do Dashboard
        receita_escritorio = _calculate_receita_escritorio(user_id, clientes)

        # DEBUG: Log detalhado dos componentes da receita escritório
        current_app.logger.info(f"🔍 ADMIN_DEBUG {user_email}: Receita Escritório Total = {receita_escritorio:.2f}")

        # Detalhar os componentes para debug
        try:
            mes_atual = datetime.now().strftime("%Y-%m")

            # Debug receita ativa
            alocacoes_res = supabase.table("alocacoes").select(
                "valor, created_at, efetivada, produtos(roa_pct)"
            ).eq("user_id", user_id).eq("efetivada", True).execute()
            alocacoes = alocacoes_res.data or []
            receita_ativa_debug = 0.0
            for alocacao in alocacoes:
                created_at = alocacao.get("created_at", "")
                if created_at.startswith(mes_atual):
                    valor = _to_float(alocacao.get("valor", 0))
                    produto = alocacao.get("produtos", {})
                    roa_pct = _to_float(produto.get("roa_pct", 0))
                    if valor > 0 and roa_pct > 0:
                        receita_ativa_debug += valor * (roa_pct / 100.0)

            # Debug receita recorrente
            receita_recorrente_debug = _calculate_receita_escritorio_recorrente(user_id, clientes)

            # Debug bônus
            bonus_debug = _calculate_bonus_ativo(user_id, mes_atual)

            current_app.logger.info(f"🔍 ADMIN_DEBUG {user_email}: Ativa={receita_ativa_debug:.2f} + Recorrente={receita_recorrente_debug:.2f} + Bônus={bonus_debug:.2f}")

        except Exception as debug_e:
            current_app.logger.error(f"❌ ADMIN_DEBUG {user_email}: Erro no debug: {debug_e}")

        # Receita Assessor: usando lógica do Dashboard (inclui bônus)
        receita_assessor = _calculate_receita_assessor(receita_escritorio, clientes, user_id)


        # Calcular atingimento
        atingimento_pct = (receita_escritorio / meta_mes * 100) if meta_mes > 0 else 0.0

        # Buscar nome do usuário
        user_data = _get_user_by_email(user_email)
        name = user_data.get("nome", user_email.split("@")[0]) if user_data else user_email.split("@")[0]

        return {
            "email": user_email,
            "user_id": user_id,
            "name": name,
            "penetracao_xp": penetracao_xp,
            "penetracao_mb": penetracao_mb,
            "penetracao_total": penetracao_total,
            "meta_mes": meta_mes,
            "receita_escritorio": receita_escritorio,
            "receita_assessor": receita_assessor,
            "atingimento_pct": atingimento_pct,
            "total_clientes": total_clientes,
            "xp_count": xp_count,
            "mb_count": mb_count,
            "total_clientes_com_alocacao": total_clientes_com_alocacao
        }

    except Exception as e:
        current_app.logger.error(f"Erro calculando métricas para {user_email}: {e}")
        return {
            "email": user_email,
            "user_id": user_id,
            "name": user_email.split("@")[0],
            "penetracao_xp": 0.0,
            "penetracao_mb": 0.0,
            "penetracao_total": 0.0,
            "meta_mes": 0.0,
            "receita_escritorio": 0.0,
            "receita_assessor": 0.0,
            "atingimento_pct": 0.0,
            "error": f"Erro: {str(e)}"
        }

@admin_bp.route("/", methods=["GET"])
@_admin_required
def index():
    """Tela principal administrativa com métricas consolidadas"""

    if not supabase:
        return render_template('admin/index.html',
                             error="Supabase indisponível",
                             usuarios_metricas=[],
                             mes_atual=datetime.now().strftime("%Y-%m"))

    # DEBUG: Listar todos os usuários disponíveis na tabela
    try:
        all_users_res = supabase.table("profiles").select("id, email, nome").execute()
        all_users = all_users_res.data or []
    except Exception as e:
        current_app.logger.error(f"❌ ADMIN_DEBUG: Erro ao listar usuários: {e}")

    usuarios_metricas = []
    mes_atual = datetime.now().strftime("%Y-%m")

    # Buscar user_id para cada email
    for email in USUARIOS_MONITORADOS:
        user_data = _get_user_by_email(email)
        user_id = user_data.get("id") if user_data else None


        if user_id:
            metricas = _calculate_user_metrics(user_id, email)
            usuarios_metricas.append(metricas)
        else:
            # Usuário não encontrado
            usuarios_metricas.append({
                "email": email,
                "user_id": None,
                "name": email.split("@")[0],
                "penetracao_xp": 0.0,
                "penetracao_mb": 0.0,
                "penetracao_total": 0.0,
                "meta_mes": 0.0,
                "receita_escritorio": 0.0,
                "receita_assessor": 0.0,
                "atingimento_pct": 0.0,
                "error": "Usuário não encontrado"
            })

    # Ordenar por nome para exibição consistente
    usuarios_metricas.sort(key=lambda x: x.get("name", "").lower())

    # Calcular totais consolidados
    total_receita_escritorio = sum(u.get("receita_escritorio", 0) for u in usuarios_metricas)
    total_receita_assessor = sum(u.get("receita_assessor", 0) for u in usuarios_metricas)
    total_meta = sum(u.get("meta_mes", 0) for u in usuarios_metricas)
    atingimento_geral = (total_receita_escritorio / total_meta * 100) if total_meta > 0 else 0.0

    return render_template('admin/index.html',
                         usuarios_metricas=usuarios_metricas,
                         mes_atual=mes_atual,
                         total_receita_escritorio=total_receita_escritorio,
                         total_receita_assessor=total_receita_assessor,
                         total_meta=total_meta,
                         atingimento_geral=atingimento_geral,
                         total_usuarios=len(usuarios_metricas))