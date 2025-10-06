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
import hashlib
import time

try:
    from supabase_client import supabase, get_supabase_client
    from cache_manager import cache
except Exception:
    supabase = None
    cache = None

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

def _receita_escritorio_mes_atual_via_alocacoes_admin(user_id):
    """
    EXATA função do Dashboard _receita_escritorio_mes_atual_via_alocacoes
    adaptada para admin (com user_id específico)
    """
    if not supabase:
        return 0.0

    mes_atual = datetime.today().strftime("%Y-%m")
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

        current_app.logger.debug("ADMIN_RECEITA_ATIVA: Valor=%.2f × ROA=%.2f%% = Receita=%.2f",
                                valor, roa_pct, receita_item)

    current_app.logger.info("ADMIN_RECEITA_ATIVA_TOTAL: %.2f (de %d alocações analisadas) - user_id: %s",
                           total, len(rows), user_id)
    return total

def _receita_assessor_recorrente_admin(user_id):
    """
    EXATA função do Dashboard _receita_assessor_recorrente adaptada para admin
    """
    if not supabase:
        return 0.0

    import json

    try:
        # Buscar o último mês com dados na tabela
        res_meses = (supabase.table("receita_itens")
                    .select("data_ref")
                    .eq("user_id", user_id)
                    .order("data_ref", desc=True)
                    .limit(1)
                    .execute())

        if not res_meses.data:
            current_app.logger.info("ADMIN_RECEITA_PASSIVA: Nenhum dado encontrado na tabela receita_itens para user_id: %s", user_id)
            return 0.0

        ultimo_mes_disponivel = res_meses.data[0].get("data_ref", "")
        if not ultimo_mes_disponivel:
            return 0.0

        # Extrair YYYY-MM do último mês
        mes_target = ultimo_mes_disponivel[:7]  # YYYY-MM

        current_app.logger.info("ADMIN_RECEITA_PASSIVA: Último mês disponível: %s (extraído: %s) - user_id: %s",
                               ultimo_mes_disponivel, mes_target, user_id)

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

        current_app.logger.info("ADMIN_RECEITA_PASSIVA: Produtos selecionados como recorrentes: %s - user_id: %s",
                               list(selected_set), user_id)

        # Buscar receitas do último mês disponível
        res_receitas = supabase.table("receita_itens").select(
            "valor_liquido, produto, familia"
        ).eq("user_id", user_id).like("data_ref", f"{mes_target}%").execute()

        total_passiva = 0.0
        items_processados = 0
        items_recorrentes = 0
        items_admin_ignorados = 0

        # Função para verificar família administrativa (mesma do Dashboard)
        def _is_admin_family(fam):
            fam_lower = fam.lower()
            return any(x in fam_lower for x in ["admin", "corretagem", "custódia", "escritório"])

        for receita in res_receitas.data or []:
            items_processados += 1
            produto = (receita.get("produto") or "").strip()
            familia = (receita.get("familia") or "").strip()
            val_liq = _to_float(receita.get("valor_liquido"))

            # Pular família administrativa
            if _is_admin_family(familia):
                items_admin_ignorados += 1
                continue

            # Lógica EXATA do Dashboard
            produto_presente = bool(produto)

            if not produto_presente:
                # Se não tem produto, conta como recorrente
                total_passiva += val_liq
                items_recorrentes += 1
                current_app.logger.debug("ADMIN_RECEITA_PASSIVA: Sem produto -> recorrente: R$ %.2f", val_liq)
            else:
                # Se tem produto, só conta se estiver nas categorias selecionadas
                if not selected_set or (produto in selected_set):
                    total_passiva += val_liq
                    items_recorrentes += 1
                    current_app.logger.debug("ADMIN_RECEITA_PASSIVA: Produto %s -> recorrente: R$ %.2f", produto, val_liq)

        current_app.logger.info("ADMIN_RECEITA_PASSIVA: Processados=%d, Recorrentes=%d, Admin ignorados=%d, Total=R$ %.2f - user_id: %s",
                               items_processados, items_recorrentes, items_admin_ignorados, total_passiva, user_id)

        return total_passiva

    except Exception as e:
        current_app.logger.error("ADMIN_RECEITA_PASSIVA: Erro para user_id %s: %s", user_id, e)
        return 0.0

def _receita_escritorio_recorrente_admin(clientes, user_id):
    """
    EXATA função do Dashboard _receita_escritorio_recorrente adaptada para admin
    """
    receita_assessor_rec = _receita_assessor_recorrente_admin(user_id)

    current_app.logger.info("ADMIN_RECEITA_ESCRIT_REC: Receita assessor recorrente = %.2f - user_id: %s",
                           receita_assessor_rec, user_id)

    if receita_assessor_rec <= 0:
        current_app.logger.warning("ADMIN_RECEITA_ESCRIT_REC: Receita assessor recorrente = 0, retornando 0 - user_id: %s", user_id)
        return 0.0

    if not clientes:
        current_app.logger.warning("ADMIN_RECEITA_ESCRIT_REC: Sem clientes para calcular média ponderada - user_id: %s", user_id)
        return 0.0

    # Verificar se campo repasse existe nos clientes
    if 'repasse' not in clientes[0]:
        current_app.logger.error("ADMIN_RECEITA_ESCRIT_REC: Campo 'repasse' não encontrado nos clientes! - user_id: %s", user_id)
        return 0.0

    # Calcular média ponderada (mesmo cálculo usado em _receita_assessor_mes)
    total_net = 0.0
    total_net_ponderado = 0.0
    clientes_com_net = 0
    clientes_com_repasse = 0

    for i, cliente in enumerate(clientes):
        net_total = _to_float(cliente.get("net_total"))
        repasse = _to_float(cliente.get("repasse"))
        nome = cliente.get("nome", "N/A")[:30]

        if net_total > 0:
            clientes_com_net += 1
            total_net += net_total
            if repasse > 0:
                clientes_com_repasse += 1
                ponderado_cliente = (net_total * repasse / 100.0)
                total_net_ponderado += ponderado_cliente

                # Debug apenas dos primeiros 3 clientes
                if i < 3:
                    current_app.logger.info("ADMIN_RECEITA_ESCRIT_REC: Cliente %d: %s - NET=%.2f, repasse=%.2f%%, ponderado=%.2f - user_id: %s",
                                           i+1, nome, net_total, repasse, ponderado_cliente, user_id)

    current_app.logger.info("ADMIN_RECEITA_ESCRIT_REC: %d clientes total, %d com NET>0, %d com repasse>0 - user_id: %s",
                           len(clientes), clientes_com_net, clientes_com_repasse, user_id)

    if total_net == 0:
        current_app.logger.warning("ADMIN_RECEITA_ESCRIT_REC: Nenhum cliente com NET > 0 - user_id: %s", user_id)
        return 0.0

    if total_net_ponderado == 0:
        current_app.logger.warning("ADMIN_RECEITA_ESCRIT_REC: Total NET ponderado = 0 - user_id: %s", user_id)
        return 0.0

    media_ponderada_repasse = total_net_ponderado / total_net

    # Fórmula inversa: Receita Escritório = Receita Assessor ÷ 80% ÷ Média Ponderada
    receita_escritorio_rec = receita_assessor_rec / 0.80 / media_ponderada_repasse

    current_app.logger.info("ADMIN_RECEITA_ESCRIT_REC: %.2f ÷ 80%% ÷ %.4f = %.2f - user_id: %s",
                           receita_assessor_rec, media_ponderada_repasse, receita_escritorio_rec, user_id)

    return receita_escritorio_rec

def _carregar_bonus_ativo_mes_admin(user_id):
    """
    EXATA função do Dashboard _carregar_bonus_ativo_mes adaptada para admin
    """
    if not supabase or not user_id:
        return 0.0

    def _calcular_valor_liquido_bonus(valor_bonus, liquido_assessor):
        """
        Calcula o valor líquido do bônus para o assessor.
        Se liquido_assessor = True: retorna o valor como está
        Se liquido_assessor = False: aplica 80% (desconta 20% de IR)
        """
        if liquido_assessor:
            return valor_bonus
        else:
            return valor_bonus * 0.80

    mes_atual = datetime.now().strftime("%Y-%m")
    total_bonus = 0.0

    try:
        # Tentar com colunas novas primeiro
        try:
            resp = supabase.table("bonus_missoes").select("valor_bonus, liquido_assessor").eq("user_id", user_id).eq("mes", mes_atual).eq("ativo", True).execute()
            bonus_list = resp.data or []
            total_bonus = sum(
                _calcular_valor_liquido_bonus(
                    b.get("valor_bonus", 0),
                    b.get("liquido_assessor", True)
                )
                for b in bonus_list
            )
        except Exception:
            # Fallback para apenas valor_bonus (sem cálculo de IR)
            resp = supabase.table("bonus_missoes").select("valor_bonus").eq("user_id", user_id).eq("mes", mes_atual).eq("ativo", True).execute()
            bonus_list = resp.data or []
            total_bonus = sum(_to_float(b.get("valor_bonus", 0)) for b in bonus_list)
            current_app.logger.warning("ADMIN_BONUS: Usando fallback (campos novos não disponíveis) - user_id: %s", user_id)

        current_app.logger.info("ADMIN_BONUS: Total bônus ativo do mês: R$ %.2f - user_id: %s", total_bonus, user_id)
    except Exception as e:
        current_app.logger.warning("ADMIN_BONUS: Erro ao carregar bônus para user_id %s: %s", user_id, e)

    return total_bonus

def _receita_escritorio_total_mes_admin(clientes, user_id):
    """
    EXATA função do Dashboard _receita_escritorio_total_mes adaptada para admin
    Calcula a receita total do escritório no mês atual:
    Receita Ativa (alocações EFETIVADAS) + Receita Recorrente (calculada a partir da receita assessor) + Bônus
    """
    receita_ativa = _receita_escritorio_mes_atual_via_alocacoes_admin(user_id)
    receita_recorrente = _receita_escritorio_recorrente_admin(clientes, user_id)
    bonus_ativo = _carregar_bonus_ativo_mes_admin(user_id)

    total = receita_ativa + receita_recorrente + bonus_ativo

    current_app.logger.info("ADMIN_RECEITA_ESCRIT_TOTAL: Ativa=%.2f (alocações) + Recorrente=%.2f + Bônus=%.2f = Total=%.2f - user_id: %s",
                           receita_ativa, receita_recorrente, bonus_ativo, total, user_id)

    return total

def _receita_assessor_mes_admin(receita_escritorio: float, clientes, user_id):
    """
    EXATA função do Dashboard _receita_assessor_mes adaptada para admin
    Calcula a receita do assessor no mês usando a fórmula:
    Receita Assessor = Receita Escritório × 80% × (Média Ponderada do NET × Repasse)
    Média Ponderada = Σ(NET_cliente × Repasse_cliente) / Σ(NET_cliente)
    """
    current_app.logger.info("ADMIN_RECEITA_ASSESSOR: Iniciando cálculo - Receita Escritório: %.2f, Clientes: %d - user_id: %s",
                           receita_escritorio, len(clientes) if clientes else 0, user_id)

    if not clientes:
        current_app.logger.warning("ADMIN_RECEITA_ASSESSOR: Lista de clientes vazia - user_id: %s", user_id)
        return 0.0

    if receita_escritorio <= 0:
        current_app.logger.warning("ADMIN_RECEITA_ASSESSOR: Receita escritório <= 0: %.2f - user_id: %s", receita_escritorio, user_id)
        return 0.0

    total_net = 0.0
    total_net_ponderado = 0.0
    clientes_validos = 0
    clientes_sem_repasse = 0

    # Verificar se campo repasse existe nos clientes
    if clientes and 'repasse' not in clientes[0]:
        current_app.logger.error("ADMIN_RECEITA_ASSESSOR: Campo 'repasse' não encontrado nos clientes! - user_id: %s", user_id)
        return 0.0

    for i, cliente in enumerate(clientes):
        nome = cliente.get("nome", "Sem nome")[:30]  # Primeiros 30 chars
        net_total = _to_float(cliente.get("net_total"))
        repasse = _to_float(cliente.get("repasse"))

        if net_total > 0:
            clientes_validos += 1
            total_net += net_total

            if repasse > 0:
                ponderado = net_total * (repasse / 100.0)
                total_net_ponderado += ponderado

                # Debug apenas dos primeiros 3 clientes
                if i < 3:
                    current_app.logger.info("ADMIN_RECEITA_ASSESSOR: Cliente %d: %s - NET: %.2f, Repasse: %.2f%%, Ponderado: %.2f - user_id: %s",
                                           i+1, nome, net_total, repasse, ponderado, user_id)
            else:
                clientes_sem_repasse += 1

    current_app.logger.info("ADMIN_RECEITA_ASSESSOR: %d clientes válidos (NET > 0), %d sem repasse - user_id: %s",
                           clientes_validos, clientes_sem_repasse, user_id)

    if total_net <= 0:
        current_app.logger.warning("ADMIN_RECEITA_ASSESSOR: Total NET <= 0 - user_id: %s", user_id)
        return 0.0

    if total_net_ponderado <= 0:
        current_app.logger.warning("ADMIN_RECEITA_ASSESSOR: Total ponderado <= 0. Todos os clientes estão sem repasse? - user_id: %s", user_id)
        return 0.0

    # Calcular média ponderada
    media_ponderada = total_net_ponderado / total_net

    # Fórmula base (sem bônus)
    receita_assessor_base = receita_escritorio * 0.80 * media_ponderada

    # Adicionar bônus ativos do mês (EXATAMENTE como no Dashboard)
    bonus_ativo = _carregar_bonus_ativo_mes_admin(user_id)
    receita_assessor = receita_assessor_base + bonus_ativo

    current_app.logger.info("ADMIN_RECEITA_ASSESSOR: Total NET: %.2f, Ponderado: %.2f, Média: %.4f (%.2f%%) - user_id: %s",
                           total_net, total_net_ponderado, media_ponderada, media_ponderada * 100, user_id)
    current_app.logger.info("ADMIN_RECEITA_ASSESSOR: Base: %.2f × 80%% × %.4f = %.2f - user_id: %s",
                           receita_escritorio, media_ponderada, receita_assessor_base, user_id)
    current_app.logger.info("ADMIN_RECEITA_ASSESSOR: Bônus ativo: R$ %.2f | Receita total: R$ %.2f - user_id: %s",
                           bonus_ativo, receita_assessor, user_id)

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

        # Calcular receita usando EXATAMENTE a mesma lógica do Dashboard
        receita_escritorio = _receita_escritorio_total_mes_admin(clientes, user_id)

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

        # Receita Assessor: usando EXATAMENTE a lógica do Dashboard
        receita_assessor = _receita_assessor_mes_admin(receita_escritorio, clientes, user_id)


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

def _bulk_load_admin_data():
    """Carrega todos os dados necessários em lotes para otimização"""
    if not supabase:
        return {}

    # Cache key baseado no mês atual
    mes_atual = datetime.now().strftime("%Y-%m")
    cache_key = f"admin_bulk_data_{mes_atual}_{hash(str(USUARIOS_MONITORADOS))}"

    # Tentar buscar do cache (válido por 5 minutos)
    if cache:
        try:
            cached_data = cache.get(cache_key)
            if cached_data:
                current_app.logger.info("🚀 ADMIN: Usando dados do cache")
                return cached_data
        except Exception as e:
            current_app.logger.warning(f"⚠️ ADMIN: Cache read error: {e}")

    mes_atual = datetime.now().strftime("%Y-%m")

    try:
        # 1. Buscar todos os usuários monitorados de uma vez
        emails_filter = ','.join([f'"eq.{email}"' for email in USUARIOS_MONITORADOS])
        users_res = supabase.table("profiles").select("id, email, nome").or_(f"email.in.({','.join(USUARIOS_MONITORADOS)})").execute()
        users_map = {user['email']: user for user in (users_res.data or [])}

        user_ids = [user['id'] for user in users_map.values()]
        if not user_ids:
            return {'users_map': users_map}

        # 2. Buscar todos os clientes de uma vez
        clientes_res = supabase.table("clientes").select("id, user_id, nome, net_total, repasse").in_("user_id", user_ids).execute()
        clientes_by_user = defaultdict(list)
        for cliente in (clientes_res.data or []):
            if _to_float(cliente.get("net_total", 0)) > 0:
                clientes_by_user[cliente['user_id']].append(cliente)

        # 3. Buscar todas as alocações efetivadas de uma vez
        alocacoes_res = supabase.table("alocacoes").select(
            "user_id, cliente_id, valor, created_at, efetivada, produtos(classe, em_campanha, roa_pct)"
        ).in_("user_id", user_ids).eq("efetivada", True).execute()
        alocacoes_by_user = defaultdict(list)
        for alocacao in (alocacoes_res.data or []):
            alocacoes_by_user[alocacao['user_id']].append(alocacao)

        # 4. Buscar todas as metas mensais de uma vez
        metas_res = supabase.table("metas_mensais").select("user_id, meta_receita").in_("user_id", user_ids).eq("mes", mes_atual).execute()
        metas_by_user = {meta['user_id']: _to_float(meta.get('meta_receita', 0)) for meta in (metas_res.data or [])}

        # 5. Buscar todos os bônus ativos de uma vez
        try:
            bonus_res = supabase.table("bonus_missoes").select(
                "user_id, valor_bonus, liquido_assessor"
            ).in_("user_id", user_ids).eq("mes", mes_atual).eq("ativo", True).execute()
            bonus_by_user = defaultdict(float)
            for bonus in (bonus_res.data or []):
                valor_bonus = _to_float(bonus.get('valor_bonus', 0))
                liquido_assessor = bonus.get('liquido_assessor', True)
                valor_liquido = valor_bonus if liquido_assessor else valor_bonus * 0.80
                bonus_by_user[bonus['user_id']] += valor_liquido
        except Exception:
            # Fallback sem coluna liquido_assessor
            bonus_res = supabase.table("bonus_missoes").select(
                "user_id, valor_bonus"
            ).in_("user_id", user_ids).eq("mes", mes_atual).eq("ativo", True).execute()
            bonus_by_user = defaultdict(float)
            for bonus in (bonus_res.data or []):
                bonus_by_user[bonus['user_id']] += _to_float(bonus.get('valor_bonus', 0))

        # 6. Buscar receitas recorrentes (último mês disponível por usuário)
        receita_itens_res = supabase.table("receita_itens").select(
            "user_id, data_ref, valor_liquido, produto, familia"
        ).in_("user_id", user_ids).order("data_ref", desc=True).execute()

        receita_by_user = defaultdict(list)
        for item in (receita_itens_res.data or []):
            receita_by_user[item['user_id']].append(item)

        # 7. Buscar preferências de recorrência
        prefs_res = supabase.table("user_prefs").select(
            "user_id, value"
        ).in_("user_id", user_ids).eq("key", "recorrencia_produtos").execute()
        prefs_by_user = {pref['user_id']: pref.get('value') for pref in (prefs_res.data or [])}

        # Dados carregados com sucesso - salvar no cache
        bulk_data = {
            'users_map': users_map,
            'clientes_by_user': clientes_by_user,
            'alocacoes_by_user': alocacoes_by_user,
            'metas_by_user': metas_by_user,
            'bonus_by_user': bonus_by_user,
            'receita_by_user': receita_by_user,
            'prefs_by_user': prefs_by_user
        }

        # Salvar no cache por 5 minutos
        if cache:
            try:
                cache.set(cache_key, bulk_data, timeout=300)  # 5 minutos
                current_app.logger.info("💾 ADMIN: Dados salvos no cache")
            except Exception as e:
                current_app.logger.warning(f"⚠️ ADMIN: Cache write error: {e}")

        return bulk_data

    except Exception as e:
        current_app.logger.error(f"❌ ADMIN_BULK_LOAD: Erro ao carregar dados: {e}")
        return {'error': str(e)}

# Funções bulk removidas - usando diretamente as funções do Dashboard para garantir consistência

@admin_bp.route("/", methods=["GET"])
@_admin_required
def index():
    """Tela principal administrativa com métricas consolidadas (OTIMIZADA)"""

    if not supabase:
        return render_template('admin/index.html',
                             error="Supabase indisponível",
                             usuarios_metricas=[],
                             mes_atual=datetime.now().strftime("%Y-%m"))

    try:
        # Carregar todos os dados necessários de uma vez
        current_app.logger.info("🚀 ADMIN: Iniciando carregamento otimizado de dados")
        bulk_data = _bulk_load_admin_data()

        if 'error' in bulk_data:
            return render_template('admin/index.html',
                                 error=f"Erro ao carregar dados: {bulk_data['error']}",
                                 usuarios_metricas=[],
                                 mes_atual=datetime.now().strftime("%Y-%m"))

        usuarios_metricas = []
        mes_atual = datetime.now().strftime("%Y-%m")

        # Processar cada usuário com dados já carregados
        for email in USUARIOS_MONITORADOS:
            user_data = bulk_data.get('users_map', {}).get(email)

            if not user_data:
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
                continue

            user_id = user_data['id']
            name = user_data.get('nome', email.split('@')[0])

            # Dados já carregados
            clientes = bulk_data.get('clientes_by_user', {}).get(user_id, [])
            alocacoes = bulk_data.get('alocacoes_by_user', {}).get(user_id, [])
            meta_mes = bulk_data.get('metas_by_user', {}).get(user_id, 0.0)
            bonus_total = bulk_data.get('bonus_by_user', {}).get(user_id, 0.0)

            # Calcular penetração rapidamente
            total_clientes = len(clientes)
            if total_clientes == 0:
                penetracao_xp = penetracao_mb = penetracao_total = 0.0
                receita_ativa = 0.0
            else:
                # Organizar alocações por cliente
                clientes_alocacoes = defaultdict(list)
                for alocacao in alocacoes:
                    cliente_id = alocacao.get('cliente_id')
                    produto = alocacao.get('produtos', {})
                    classe = produto.get('classe', '')
                    em_campanha = produto.get('em_campanha', False)

                    is_mb = classe == "Renda Fixa Digital"
                    is_xp = classe != "Renda Fixa Digital" and em_campanha

                    clientes_alocacoes[cliente_id].append({'is_mb': is_mb, 'is_xp': is_xp})

                # Contar penetração
                clientes_xp = set()
                clientes_apenas_mb = set()

                for cliente_id, alocacoes_cliente in clientes_alocacoes.items():
                    has_mb = any(a['is_mb'] for a in alocacoes_cliente)
                    has_xp = any(a['is_xp'] for a in alocacoes_cliente)

                    if has_xp:
                        clientes_xp.add(cliente_id)
                    elif has_mb and not has_xp:
                        clientes_apenas_mb.add(cliente_id)

                penetracao_xp = (len(clientes_xp) / total_clientes * 100)
                penetracao_mb = (len(clientes_apenas_mb) / total_clientes * 100)
                penetracao_total = penetracao_xp + penetracao_mb

                # Usar EXATAMENTE as mesmas funções do Dashboard
                receita_escritorio = _receita_escritorio_total_mes_admin(clientes, user_id)
                receita_assessor = _receita_assessor_mes_admin(receita_escritorio, clientes, user_id)

            # Atingimento
            atingimento_pct = (receita_escritorio / meta_mes * 100) if meta_mes > 0 else 0.0

            usuarios_metricas.append({
                "email": email,
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
                "xp_count": len(clientes_xp) if 'clientes_xp' in locals() else 0,
                "mb_count": len(clientes_apenas_mb) if 'clientes_apenas_mb' in locals() else 0
            })

        # Ordenar e calcular totais
        usuarios_metricas.sort(key=lambda x: x.get("name", "").lower())

        total_receita_escritorio = sum(u.get("receita_escritorio", 0) for u in usuarios_metricas)
        total_receita_assessor = sum(u.get("receita_assessor", 0) for u in usuarios_metricas)
        total_meta = sum(u.get("meta_mes", 0) for u in usuarios_metricas)
        atingimento_geral = (total_receita_escritorio / total_meta * 100) if total_meta > 0 else 0.0

        current_app.logger.info(f"✅ ADMIN: Dados carregados com sucesso para {len(usuarios_metricas)} usuários")

        return render_template('admin/index.html',
                             usuarios_metricas=usuarios_metricas,
                             mes_atual=mes_atual,
                             total_receita_escritorio=total_receita_escritorio,
                             total_receita_assessor=total_receita_assessor,
                             total_meta=total_meta,
                             atingimento_geral=atingimento_geral,
                             total_usuarios=len(usuarios_metricas))

    except Exception as e:
        current_app.logger.error(f"❌ ADMIN: Erro geral: {e}")
        return render_template('admin/index.html',
                             error=f"Erro interno: {str(e)}",
                             usuarios_metricas=[],
                             mes_atual=datetime.now().strftime("%Y-%m"))

@admin_bp.route("/limpar-alocacoes-todas", methods=["POST"])
@_admin_required
def limpar_alocacoes_todas():
    """
    Limpa todas as alocações efetivadas de meses anteriores
    para TODOS os usuários monitorados (apenas admin)
    """
    if not supabase:
        from flask import jsonify
        return jsonify({"success": False, "message": "Sistema indisponível"}), 500

    try:
        # Data do primeiro dia do mês atual
        mes_atual = datetime.now().replace(day=1).strftime("%Y-%m-%d")

        total_excluidas = 0
        total_valor = 0.0
        erros = []

        # Buscar todos os user_ids dos usuários monitorados
        users_res = supabase.table("profiles").select("id, email").in_("email", USUARIOS_MONITORADOS).execute()
        users = users_res.data or []

        for user in users:
            user_id = user.get("id")
            user_email = user.get("email")

            try:
                # Buscar alocações efetivadas criadas antes do mês atual deste usuário
                resp_busca = supabase.table("alocacoes").select("id, created_at, valor").eq(
                    "user_id", user_id
                ).eq("efetivada", True).lt("created_at", mes_atual).execute()

                alocacoes_antigas = resp_busca.data or []

                if alocacoes_antigas:
                    # Excluir as alocações
                    for aloc in alocacoes_antigas:
                        supabase.table("alocacoes").delete().eq("id", aloc.get("id")).eq("user_id", user_id).execute()
                        total_valor += _to_float(aloc.get("valor", 0))
                        total_excluidas += 1

                    current_app.logger.info(f"ADMIN_LIMPAR: {len(alocacoes_antigas)} alocações excluídas para {user_email}")

            except Exception as e:
                current_app.logger.error(f"ADMIN_LIMPAR: Erro ao limpar alocações de {user_email}: {e}")
                erros.append(f"{user_email}: {str(e)}")

        # Invalidar cache global
        try:
            from cache_manager import invalidate_all_user_cache
            invalidate_all_user_cache()
        except Exception as e:
            current_app.logger.warning(f"ADMIN_LIMPAR: Erro ao invalidar cache: {e}")

        if erros:
            from flask import flash
            for erro in erros:
                flash(f"Erro: {erro}", "error")

        if total_excluidas > 0:
            from flask import flash
            flash(f"{total_excluidas} alocações antigas excluídas de todos os usuários (R$ {total_valor:,.2f})", "success")
        else:
            from flask import flash
            flash("Nenhuma alocação antiga encontrada em nenhum usuário.", "info")

    except Exception as e:
        current_app.logger.exception("ADMIN_LIMPAR: Erro geral ao limpar alocações")
        from flask import flash
        flash("Erro ao limpar alocações antigas.", "error")

    from flask import redirect, url_for
    return redirect(url_for("admin.index"))