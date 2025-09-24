from flask import Blueprint, render_template, session, current_app
from flask_login import login_required
from datetime import datetime
from utils.supabase_client import supabase
from collections import defaultdict

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def _to_float(value):
    """Converte valor para float, tratando casos especiais"""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if isinstance(value, str):
            value = value.replace(".", "").replace(",", ".")
        return float(value)
    except (ValueError, TypeError):
        return 0.0

def _admin_required(f):
    """Decorator para restringir acesso ao admin"""
    def decorated_function(*args, **kwargs):
        user_email = session.get('user', {}).get('email', '').lower()
        if user_email != 'renan.godinho@svninvest.com.br':
            current_app.logger.warning(f"🚨 ADMIN_ACCESS_DENIED: {user_email} tentou acessar painel admin")
            return render_template('404.html'), 404
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# Lista de usuários monitorados
USUARIOS_MONITORADOS = [
    "vinicius.carvalho@svninvest.com.br",
    "roberta.bonete@svninvest.com.br",
    "matheus.campos@svninvest.com.br",
    "renato.kinji@svninvest.com.br",
    "daniel.alves@svninvest.com.br",
    "leonardo.baggio@svninvest.com.br",
    "renan.godinho@svninvest.com.br"
]

def _get_all_user_metrics_optimized():
    """Versão OTIMIZADA: busca dados de todos os usuários de uma vez"""
    if not supabase:
        return []

    try:
        mes_atual = datetime.now().strftime("%Y-%m")

        # 1. QUERY ÚNICA: Buscar todos os usuários monitorados de uma vez
        users_res = supabase.table("profiles").select("id, email, nome").in_("email", USUARIOS_MONITORADOS).execute()
        users_data = {user["email"]: user for user in (users_res.data or [])}

        # 2. QUERY ÚNICA: Buscar todos os clientes de todos os usuários
        user_ids = [user["id"] for user in users_data.values()]
        clientes_res = supabase.table("clientes").select("id, user_id, nome, net_total, repasse").in_("user_id", user_ids).execute()

        # Organizar clientes por user_id
        clientes_by_user = defaultdict(list)
        for cliente in (clientes_res.data or []):
            if _to_float(cliente.get("net_total", 0)) > 0:
                clientes_by_user[cliente["user_id"]].append(cliente)

        # 3. QUERY ÚNICA: Buscar todas as alocações efetivadas de todos os usuários
        alocacoes_res = supabase.table("alocacoes").select(
            "user_id, cliente_id, produto_id, valor, produtos(classe, em_campanha)"
        ).in_("user_id", user_ids).eq("efetivada", True).execute()

        # Organizar alocações por user_id
        alocacoes_by_user = defaultdict(list)
        for alocacao in (alocacoes_res.data or []):
            alocacoes_by_user[alocacao["user_id"]].append(alocacao)

        # 4. QUERY ÚNICA: Buscar todas as metas do mês atual
        metas_res = supabase.table("metas_mensais").select("user_id, meta_receita").in_("user_id", user_ids).eq("mes", mes_atual).execute()
        metas_by_user = {meta["user_id"]: _to_float(meta.get("meta_receita", 0)) for meta in (metas_res.data or [])}

        # 5. QUERY ÚNICA: Buscar todos os bônus ativos do mês atual
        try:
            bonus_res = supabase.table("bonus_missoes").select(
                "user_id, valor_bonus, liquido_assessor"
            ).in_("user_id", user_ids).eq("mes", mes_atual).eq("ativo", True).execute()

            bonus_by_user = defaultdict(float)
            for bonus in (bonus_res.data or []):
                user_id = bonus["user_id"]
                valor_bonus = _to_float(bonus.get("valor_bonus", 0))
                liquido_assessor = bonus.get("liquido_assessor", False)
                # Aplicar lógica de IR
                valor_final = valor_bonus if liquido_assessor else valor_bonus * 0.80
                bonus_by_user[user_id] += valor_final

        except Exception:
            bonus_by_user = defaultdict(float)

        # 6. QUERY ÚNICA: Buscar receitas recorrentes (se necessário)
        # TODO: Implementar se precisar da receita recorrente

        # PROCESSAR DADOS para cada usuário
        usuarios_metricas = []

        for email in USUARIOS_MONITORADOS:
            user_data = users_data.get(email)
            if not user_data:
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
                    "total_clientes": 0,
                    "xp_count": 0,
                    "mb_count": 0,
                    "total_clientes_com_alocacao": 0,
                    "error": "Usuário não encontrado"
                })
                continue

            user_id = user_data["id"]
            clientes = clientes_by_user.get(user_id, [])
            alocacoes = alocacoes_by_user.get(user_id, [])
            meta_mes = metas_by_user.get(user_id, 0.0)
            bonus_ativo = bonus_by_user.get(user_id, 0.0)

            # Calcular métricas de penetração
            total_clientes = len(clientes)

            if total_clientes == 0:
                penetracao_xp = penetracao_mb = penetracao_total = 0.0
                xp_count = mb_count = total_clientes_com_alocacao = 0
            else:
                # Processar alocações para calcular penetrações
                clientes_alocacoes = defaultdict(list)
                for alocacao in alocacoes:
                    cliente_id = alocacao.get("cliente_id")
                    produto = alocacao.get("produtos", {})
                    classe = produto.get("classe", "")
                    em_campanha = produto.get("em_campanha", False)

                    is_mb = classe == "Renda Fixa Digital"
                    is_xp = classe != "Renda Fixa Digital" and em_campanha

                    clientes_alocacoes[cliente_id].append({
                        'is_mb': is_mb,
                        'is_xp': is_xp
                    })

                # Aplicar REGRA CORRIGIDA:
                # XP = Clientes que têm QUALQUER alocação XP
                # MB = Clientes que têm APENAS alocações MB
                clientes_xp = set()
                clientes_apenas_mb = set()

                for cliente_id, alocacoes_cliente in clientes_alocacoes.items():
                    has_mb = any(a['is_mb'] for a in alocacoes_cliente)
                    has_xp = any(a['is_xp'] for a in alocacoes_cliente)

                    if has_xp:
                        clientes_xp.add(cliente_id)

                    if has_mb and not has_xp:
                        clientes_apenas_mb.add(cliente_id)

                xp_count = len(clientes_xp)
                mb_count = len(clientes_apenas_mb)
                total_clientes_com_alocacao = len(clientes_alocacoes)

                penetracao_xp = (xp_count / total_clientes * 100) if total_clientes > 0 else 0.0
                penetracao_mb = (mb_count / total_clientes * 100) if total_clientes > 0 else 0.0
                penetracao_total = penetracao_xp + penetracao_mb

            # Calcular receitas (lógica simplificada para otimização)
            receita_ativa = 0.0
            for alocacao in alocacoes:
                valor_alocacao = _to_float(alocacao.get("valor", 0))
                receita_ativa += valor_alocacao * 0.005  # 0.5% padrão

            # Receita recorrente (simplificada - pode ser otimizada mais)
            receita_recorrente = 0.0  # TODO: Implementar se necessário

            receita_escritorio = receita_ativa + receita_recorrente + bonus_ativo

            # Receita assessor
            if not clientes or receita_escritorio <= 0:
                receita_assessor = 0.0
            else:
                total_net = sum(_to_float(c.get("net_total", 0)) for c in clientes)
                total_net_ponderado = sum(
                    _to_float(c.get("net_total", 0)) * _to_float(c.get("repasse", 0)) / 100.0
                    for c in clientes if _to_float(c.get("repasse", 0)) > 0
                )

                if total_net > 0 and total_net_ponderado > 0:
                    media_ponderada_repasse = total_net_ponderado / total_net
                    receita_assessor_base = receita_escritorio * 0.80 * media_ponderada_repasse
                    receita_assessor = receita_assessor_base + bonus_ativo
                else:
                    receita_assessor = 0.0

            # Calcular atingimento
            atingimento_pct = (receita_escritorio / meta_mes * 100) if meta_mes > 0 else 0.0

            usuarios_metricas.append({
                "email": email,
                "user_id": user_id,
                "name": user_data.get("nome", email.split("@")[0]),
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
            })

        return usuarios_metricas

    except Exception as e:
        current_app.logger.error(f"❌ ADMIN_METRICS_OPTIMIZED: Erro geral: {e}")
        return []

@admin_bp.route("/", methods=["GET"])
@login_required
@_admin_required
def index():
    """Tela principal administrativa com métricas consolidadas - VERSÃO OTIMIZADA"""

    if not supabase:
        return render_template('admin/index.html',
                             error="Supabase indisponível",
                             usuarios_metricas=[],
                             mes_atual=datetime.now().strftime("%Y-%m"))

    # VERSÃO OTIMIZADA: Uma única função que busca todos os dados
    usuarios_metricas = _get_all_user_metrics_optimized()

    mes_atual = datetime.now().strftime("%Y-%m")

    # Calcular totais
    total_meta = sum(u.get("meta_mes", 0) for u in usuarios_metricas)
    total_receita_escritorio = sum(u.get("receita_escritorio", 0) for u in usuarios_metricas)
    total_receita_assessor = sum(u.get("receita_assessor", 0) for u in usuarios_metricas)
    atingimento_geral = (total_receita_escritorio / total_meta * 100) if total_meta > 0 else 0.0

    current_app.logger.info(f"🏆 ADMIN_PANEL: Carregamento otimizado concluído - {len(usuarios_metricas)} usuários processados")

    return render_template(
        'admin/index.html',
        usuarios_metricas=usuarios_metricas,
        mes_atual=mes_atual,
        total_usuarios=len(USUARIOS_MONITORADOS),
        total_meta=total_meta,
        total_receita_escritorio=total_receita_escritorio,
        total_receita_assessor=total_receita_assessor,
        atingimento_geral=atingimento_geral
    )