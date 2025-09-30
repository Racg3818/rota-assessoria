# dashboard.py
from __future__ import annotations

from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash, session
from utils import login_required
from datetime import datetime
from collections import defaultdict
import re
import unicodedata
import os
from cache_manager import cached_by_user, invalidate_user_cache

try:
    from supabase_client import supabase, get_supabase_client
except Exception:
    supabase = None

dash_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _get_supabase():
    """
    SEGURANÇA: Obtém cliente Supabase autenticado APENAS para o usuário atual.
    Retorna None se não há usuário válido para evitar vazamento de dados.
    """
    if not get_supabase_client:
        return None
    client = get_supabase_client()
    if client is None:
        current_app.logger.debug("DASHBOARD: Cliente Supabase não disponível (usuário não autenticado)")
    return client


# =============== helpers de sessão/consulta ===============
def _current_user_id() -> str | None:
    """
    Retorna o user_id UUID válido do Supabase.
    SEGURANÇA: Sempre retorna apenas o user_id da sessão atual. NUNCA acessa dados de outros usuários.
    """
    # Usar a mesma lógica do security_middleware
    from security_middleware import get_current_user_id
    user_id = get_current_user_id()

    if user_id:
        current_app.logger.info("USERID_SECURITY: User ID da sessão: %s", user_id)
        return user_id

    # Se não temos user_id válido, isso significa que a autenticação não funcionou
    u = session.get("user") or {}
    current_app.logger.error("USERID_SECURITY: Sem user_id UUID válido na sessão! Sessão: %s", list(u.keys()))
    return None


def _with_user(q, *, table_has_id: bool = True):
    """
    Aplica .eq("user_id", uid). Se não houver uid, FALHA FECHADO.
    """
    uid = _current_user_id()
    if not uid:
        current_app.logger.error("DASHBOARD: Sem user_id na sessão - negando acesso aos dados")
        # FAIL-CLOSED: sem user_id válido, retorna query que não traz dados
        return q.eq("id", "00000000-0000-0000-0000-000000000000") if table_has_id else q.limit(0)
        
    try:
        current_app.logger.info("DASHBOARD: Aplicando filtro user_id=%s", uid)
        return q.eq("user_id", uid)
    except Exception as e:
        current_app.logger.error("DASHBOARD: Erro ao filtrar por user_id: %s - negando acesso", e)
        # FAIL-CLOSED: em caso de erro, nega acesso aos dados
        return q.eq("id", "00000000-0000-0000-0000-000000000000") if table_has_id else q.limit(0)



# ---------------- helpers numéricos/strings ----------------
def _to_float(x) -> float:
    if isinstance(x, (int, float)):
        try:
            return float(x)
        except Exception:
            return 0.0
    if x is None:
        return 0.0
    s = str(x).strip()
    if s == "" or s.upper() == "NULL":
        return 0.0
    try:
        return float(s)
    except Exception:
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0


def _calcular_valor_liquido_bonus(valor_bonus, liquido_assessor):
    """
    Calcula o valor líquido do bônus para o assessor.
    Se liquido_assessor = True: retorna o valor como está
    Se liquido_assessor = False: aplica 80% (desconta 20% de IR)
    """
    if liquido_assessor:
        return _to_float(valor_bonus)
    else:
        return _to_float(valor_bonus) * 0.80

def _carregar_bonus_ativo_mes():
    """Carrega total de bônus ativos do usuário para o mês atual"""
    from datetime import datetime
    uid = _current_user_id()
    supabase = _get_supabase()
    mes_atual = datetime.now().strftime("%Y-%m")
    total_bonus = 0.0

    if supabase and uid:
        try:
            # Tentar com colunas novas primeiro
            try:
                resp = supabase.table("bonus_missoes").select("valor_bonus, liquido_assessor").eq("user_id", uid).eq("mes", mes_atual).eq("ativo", True).execute()
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
                resp = supabase.table("bonus_missoes").select("valor_bonus").eq("user_id", uid).eq("mes", mes_atual).eq("ativo", True).execute()
                bonus_list = resp.data or []
                total_bonus = sum(_to_float(b.get("valor_bonus", 0)) for b in bonus_list)
                current_app.logger.warning("BONUS_DASHBOARD: Usando fallback (campos novos não disponíveis)")

            current_app.logger.info("BONUS_DASHBOARD: Total bônus ativo do mês: R$ %.2f", total_bonus)
        except Exception as e:
            current_app.logger.warning("BONUS_DASHBOARD: Erro ao carregar bônus (tabela pode não existir): %s", e)
            total_bonus = 0.0

    return total_bonus


def _median(vals):
    arr = sorted([_to_float(v) for v in vals if v is not None])
    n = len(arr)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return arr[mid]
    return (arr[mid - 1] + arr[mid]) / 2.0


def _digits_only(s: str) -> str:
    if not s:
        return ""
    return "".join(re.findall(r"\d+", str(s)))


def _norm_name(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s.strip()


# ---------------- consultas com filtro por usuário ----------------
def _fetch_clientes_otimizado():
    """
    Busca clientes com dados otimizados para o dashboard.
    Reduz consultas separadas ao Supabase.
    """
    supabase = _get_supabase()
    if not supabase:
        current_app.logger.warning("_fetch_clientes_otimizado: cliente Supabase indisponível")
        return []

    uid = _current_user_id()
    if not uid:
        current_app.logger.error("_fetch_clientes_otimizado: user_id inválido")
        return []

    try:
        # Buscar todos os clientes com campos necessários de uma vez
        # Incluindo repasse que é essencial para cálculos ponderados
        result = supabase.table("clientes").select(
            "id, nome, codigo_xp, codigo_mb, modelo, net_total, repasse, "
            "created_at"
        ).eq("user_id", uid).order("nome").execute()

        clientes = result.data or []
        current_app.logger.info("_fetch_clientes_otimizado: %d clientes carregados", len(clientes))

        # Debug: log alguns clientes para verificar dados
        if clientes:
            sample_cliente = clientes[0]
            current_app.logger.info("_fetch_clientes_otimizado: Exemplo cliente: %s (NET: %s)",
                                   sample_cliente.get('nome', 'N/A'),
                                   sample_cliente.get('net_total', 'N/A'))

        return clientes

    except Exception as e:
        current_app.logger.exception("_fetch_clientes_otimizado: erro ao buscar clientes: %s", e)
        return []

def _fetch_clientes():
    supabase = _get_supabase()
    if not supabase:
        return []
    try:
        q = (
            supabase.table("clientes")
            .select("id,nome,modelo,repasse,net_total,net_xp,net_xp_global,net_mb,codigo_xp,codigo_mb")
        )
        q = _with_user(q)  # <-- filtra por user_id quando existir
        res = q.range(0, 200000).execute()
        return list(res.data or [])
    except Exception as e:
        current_app.logger.error("dashboard: falha ao buscar clientes (%s)", e)
        return []


def _net_by_modelo(clientes):
    out = defaultdict(float)
    for c in clientes:
        out[(c.get("modelo") or "").strip() or "SEM_MODELO"] += _to_float(c.get("net_total"))
    return dict(out)


def _select_receita_table():
    # Esta função usa o cliente administrativo para verificar existência de tabelas
    supabase = _get_supabase()
    assert supabase is not None
    primary = "receita_itens"
    fallback = "receita_intens"

    try:
        supabase.table(primary).select("cliente_codigo").limit(1).execute()
        return primary
    except Exception:
        try:
            supabase.table(fallback).select("cliente_codigo").limit(1).execute()
            current_app.logger.info("dashboard: usando tabela fallback '%s'", fallback)
            return fallback
        except Exception as e:
            current_app.logger.error("dashboard: nenhuma tabela de receita encontrada (%s)", e)
            return primary


# Rota desabilitada - metas agora são gerenciadas via Metas Escritório
# @dash_bp.route("/salvar-meta", methods=["POST"], strict_slashes=False)
# @login_required
def salvar_meta_deprecated():
    mes = (request.form.get("mes") or "").strip()
    try:
        meta_receita = float(request.form.get("meta_receita") or 0)
    except ValueError:
        meta_receita = 0.0

    uid = _current_user_id()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for("dashboard.index"))

    try:
        # ESTRATÉGIA HÍBRIDA: Tenta autenticado primeiro, fallback para admin se necessário
        client = get_supabase_client()
        current_app.logger.info("SAVE_META: Tentando salvar com cliente autenticado")
        
        try:
            # Tenta com cliente autenticado (RLS + trigger)
            existing = client.table("metas_mensais").select("id").eq("mes", mes).limit(1).execute()
            
            if existing.data:
                result = client.table("metas_mensais").update({
                    "meta_receita": meta_receita
                }).eq("mes", mes).execute()
                current_app.logger.info("SAVE_META: Meta atualizada via cliente autenticado")
            else:
                result = client.table("metas_mensais").insert({
                    "mes": mes,
                    "meta_receita": meta_receita
                }).execute()
                current_app.logger.info("SAVE_META: Meta criada via cliente autenticado")
            
            # Invalidar cache do dashboard
            invalidate_user_cache('dashboard_data')

            flash(f"Meta de {mes} salva com sucesso.", "success")
            
        except Exception as auth_error:
            current_app.logger.warning("SAVE_META: Cliente autenticado falhou: %s", auth_error)
            flash(f"Erro ao salvar meta: {auth_error}", "error")
            raise
        
    except Exception as e:
        current_app.logger.exception("SAVE_META: Todas as estratégias falharam: %s", e)
        flash("Falha ao salvar meta. Verifique os logs para mais detalhes.", "error")

    return redirect(url_for("dashboard.index"))


def _receita_ytd_por_cliente(clientes, *, force_base_table: bool = False):
    from collections import defaultdict
    from datetime import datetime
    import re

    def _norm_ym(raw: str) -> str:
        m = re.match(r"^(\d{4})-(\d{1,2})$", (raw or "").strip())
        if not m:
            return (raw or "").strip()
        y, mm = m.groups()
        return f"{y}-{int(mm):02d}"

    supabase = _get_supabase()
    totais_by_id: dict[str, float] = defaultdict(float)
    mediana_ytd = 0.0

    if not supabase:
        return dict(totais_by_id), mediana_ytd

    year = int(datetime.today().strftime("%Y"))
    start_ym = f"{year}-01"
    next_year_start = f"{year + 1}-01"

    table_name_auto = _select_receita_table()
    force_env = os.getenv("RECEITA_FORCE_BASE", "").strip() in ("1", "true", "True")
    table_name = "receita_itens" if (force_base_table or force_env) else table_name_auto

    current_app.logger.info(
        "[RECEITA_YTD] usando table_name=%s (auto=%s, force=%s)",
        table_name, table_name_auto, force_base_table or force_env
    )

    # ---- HEAD (count) com filtro por user ----
    try:
        q_head = (
            supabase.table(table_name)
            .select("data_ref", count="exact")
            .gte("data_ref", start_ym)
            .lt("data_ref", next_year_start)
        )
        q_head = _with_user(q_head)
        head = q_head.limit(1).execute()
        total_expected = (head.count or 0)
    except Exception as e:
        current_app.logger.warning("[RECEITA_YTD] falha ao obter count em %s: %s", table_name, e)
        total_expected = -1

    soma_por_codigo: dict[str, float] = defaultdict(float)
    meses_count: dict[str, int] = defaultdict(int)

    LIMIT_PAGE = 1000
    offset = 0

    while True:
        try:
            q = (
                supabase.table(table_name)
                .select("data_ref, cliente_codigo, comissao_escritorio")
                .gte("data_ref", start_ym)
                .lt("data_ref", next_year_start)
                .order("data_ref", desc=False)
            )
            q = _with_user(q)
            res = q.range(offset, offset + LIMIT_PAGE - 1).execute()
        except Exception as e:
            current_app.logger.info("dashboard: falha ao buscar %s (%s)", table_name, e)
            break

        rows = list(res.data or [])
        if not rows:
            break

        for r in rows:
            raw = (r.get("data_ref") or "").strip()
            ym = _norm_ym(raw)
            if ym:
                meses_count[ym] += 1

            codigo = _digits_only(r.get("cliente_codigo") or "")
            if not codigo:
                continue

            valor = _to_float(r.get("comissao_escritorio")) or 0.0
            soma_por_codigo[codigo] += valor

        offset += len(rows)

        if total_expected >= 0 and offset >= total_expected:
            break

        if offset > 2_000_000:
            current_app.logger.warning("dashboard: limite de paginação atingido (%s)", offset)
            break

    if meses_count:
        meses_ordenados = sorted(meses_count.keys())
        current_app.logger.info("[RECEITA_YTD] Meses lidos no ano %s: %s", year, ", ".join(meses_ordenados))
        current_app.logger.info(
            "[RECEITA_YTD] Total lido=%s; total esperado (count)=%s",
            sum(meses_count.values()), total_expected
        )
    else:
        current_app.logger.info("[RECEITA_YTD] Nenhum registro no intervalo %s..%s em %s",
                                start_ym, next_year_start, table_name)

    # ---- Projeção por cliente (somando XP + MB) ----
    for c in clientes:
        cid = c.get("id")
        if not cid:
            continue

        xp = _digits_only(c.get("codigo_xp") or "")
        mb = _digits_only(c.get("codigo_mb") or "")

        total_cliente = 0.0
        if xp:
            total_cliente += soma_por_codigo.get(xp, 0.0)
        if mb:
            total_cliente += soma_por_codigo.get(mb, 0.0)

        totais_by_id[cid] = total_cliente

    vals_pos = [v for v in totais_by_id.values() if v > 0]
    mediana_ytd = _median(vals_pos)

    return dict(totais_by_id), mediana_ytd


def _receita_assessor_esperada(meta_mes: float, clientes) -> float:
    """
    Calcula a receita assessor esperada baseada na meta do mês.
    Fórmula: Meta × 80% × Média Ponderada de Repasse da Carteira

    Args:
        meta_mes: Meta de receita do mês em reais
        clientes: Lista de clientes com NET e repasse

    Returns:
        Receita assessor esperada em reais
    """
    current_app.logger.info("RECEITA_ASSESSOR_ESPERADA: Iniciando cálculo - Meta: %.2f, Clientes: %d",
                           meta_mes, len(clientes) if clientes else 0)

    if not clientes:
        current_app.logger.warning("RECEITA_ASSESSOR_ESPERADA: Lista de clientes vazia")
        return 0.0

    if meta_mes <= 0:
        current_app.logger.warning("RECEITA_ASSESSOR_ESPERADA: Meta <= 0: %.2f", meta_mes)
        return 0.0

    total_net = 0.0
    total_net_ponderado = 0.0
    clientes_validos = 0

    # Verificar se campo repasse existe nos clientes
    if clientes and 'repasse' not in clientes[0]:
        current_app.logger.error("RECEITA_ASSESSOR_ESPERADA: Campo 'repasse' não encontrado nos clientes! Campos disponíveis: %s",
                                list(clientes[0].keys()) if clientes else [])
        return 0.0

    for cliente in clientes:
        net_total = _to_float(cliente.get("net_total"))
        repasse = _to_float(cliente.get("repasse"))

        # Só considerar clientes com NET > 0
        if net_total > 0:
            clientes_validos += 1
            total_net += net_total

            if repasse > 0:
                contribution = net_total * repasse / 100.0
                total_net_ponderado += contribution

    if total_net <= 0:
        current_app.logger.warning("RECEITA_ASSESSOR_ESPERADA: Total NET = 0, não é possível calcular média ponderada")
        return 0.0

    # Calcular média ponderada de repasse
    media_ponderada_repasse = total_net_ponderado / total_net

    # Fórmula: Meta × 80% × Média Ponderada
    receita_assessor_esperada = meta_mes * 0.80 * media_ponderada_repasse

    current_app.logger.info("RECEITA_ASSESSOR_ESPERADA: Média ponderada: %.4f (%.2f%%) | Resultado: %.2f × 80%% × %.4f = %.2f",
                           media_ponderada_repasse, media_ponderada_repasse * 100,
                           meta_mes, media_ponderada_repasse, receita_assessor_esperada)

    return receita_assessor_esperada


def _meta_do_mes():
    # SEGURANÇA: Usar APENAS cliente autenticado para evitar vazamentos
    supabase = _get_supabase()
    mes = datetime.today().strftime("%Y-%m")
    current_app.logger.info("META_DEBUG: === INICIANDO BUSCA PARA MES=%s ===", mes)

    # Debug da sessão completa
    user_session = session.get("user", {})
    current_app.logger.info("META_DEBUG: Sessão completa - email: %s, nome: %s, codigo_xp: %s",
                           user_session.get("email"), user_session.get("nome"), user_session.get("codigo_xp"))

    if not supabase:
        current_app.logger.error("META_DEBUG: ACESSO NEGADO - Cliente Supabase autenticado não disponível")
        return mes, 0.0

    uid = _current_user_id()
    current_app.logger.info("META_DEBUG: user_id obtido da função _current_user_id(): %s", uid)

    if not uid:
        current_app.logger.error("META_DEBUG: ACESSO NEGADO - Sem user_id válido na sessão!")
        return mes, 0.0

    try:
        # SEGURANÇA: Usar APENAS cliente autenticado com RLS ativo
        current_app.logger.info("META_DEBUG: Usando cliente autenticado com RLS para user_id=%s", uid)

        res = (
            supabase.table("metas_mensais")
            .select("mes,meta_receita,user_id")
            .eq("mes", mes)
            .eq("user_id", uid)  # FILTRO EXPLÍCITO OBRIGATÓRIO
            .limit(1)
            .execute()
        )
        data = res.data or []
        current_app.logger.info("META_DEBUG: Query com filtro explícito retornou %d registros: %s", len(data), data)
        
        if data:
            meta_encontrada = data[0]
            meta_valor = _to_float(meta_encontrada.get("meta_receita"))
            meta_user_id = meta_encontrada.get("user_id")
            
            # VALIDAÇÃO ADICIONAL: Confirmar que o user_id da meta é o mesmo da sessão
            if meta_user_id == uid:
                current_app.logger.info("META_DEBUG: ✅ Meta VÁLIDA encontrada! user_id=%s, valor=%s", meta_user_id, meta_valor)
                return meta_encontrada.get("mes") or mes, meta_valor
            else:
                current_app.logger.error("META_DEBUG: 🚨 VAZAMENTO DETECTADO! Meta user_id=%s, sessão user_id=%s", meta_user_id, uid)
                return mes, 0.0
        else:
            current_app.logger.warning("META_DEBUG: Nenhuma meta encontrada para user_id=%s, mes=%s", uid, mes)
            
            # SEGURANÇA: Não fazer debug de TODAS as metas (vazamento de dados)
            current_app.logger.info("META_DEBUG: Nenhuma meta encontrada para o usuário atual")
            
    except Exception as e:
        current_app.logger.error("META_DEBUG: Erro ao buscar meta: %s", e)
    
    return mes, 0.0


def _receita_escritorio_mes_atual_via_alocacoes():
    """
    Soma da receita do escritório no mês atual considerando somente
    alocações efetivadas. Usa o ROA do produto (produtos.roa_pct).
    Receita = valor * (roa_pct / 100).
    """
    supabase = _get_supabase()
    if not supabase:
        return 0.0

    mes_atual = datetime.today().strftime("%Y-%m")
    total = 0.0

    try:
        q = supabase.table("alocacoes").select(
            "valor, created_at, efetivada, produto:produto_id ( roa_pct )"
        )
        q = _with_user(q)  # <-- filtra por user_id quando existir
        res = q.execute()
        rows = list(res.data or [])
    except Exception as e:
        current_app.logger.info("dashboard: falha ao buscar alocacoes (%s)", e)
        rows = []

    for r in rows:
        # IMPORTANTE: Só considerar alocações EFETIVADAS
        efetivada = r.get("efetivada")
        if not efetivada:  # Se não efetivada, pular
            continue

        # Para receita ativa do mês, considerar alocações criadas OU efetivadas no mês atual
        # (Uma alocação pode ter sido criada em mês anterior mas efetivada agora)
        created_month = (r.get("created_at") or "")[:7]
        # TODO: Se tivermos campo 'efetivada_at', usar ele também

        if created_month != mes_atual:
            # Por enquanto, manter lógica original (apenas created_at)
            # Mas adicionar log para debug
            current_app.logger.debug("RECEITA_ATIVA: Alocação criada em %s (mês atual: %s) - ignorando",
                                    created_month, mes_atual)
            continue

        valor = _to_float(r.get("valor"))
        produto = r.get("produto") or {}
        roa_pct = _to_float(produto.get("roa_pct"))

        receita_item = valor * (roa_pct / 100.0)
        total += receita_item

        current_app.logger.debug("RECEITA_ATIVA: Valor=%.2f × ROA=%.2f%% = Receita=%.2f",
                                valor, roa_pct, receita_item)

    current_app.logger.info("RECEITA_ATIVA_TOTAL: %.2f (de %d alocações analisadas)",
                           total, len(rows))
    return total


def _receita_assessor_recorrente():
    """
    Calcula a receita ASSESSOR recorrente do último mês DISPONÍVEL na tabela receita_itens.
    Busca o mês mais recente na coluna data_ref e usa a mesma lógica da tela de Receita.
    RETORNA: Receita do assessor (já é a receita líquida recorrente).
    """
    supabase = _get_supabase()
    if not supabase:
        return 0.0
    
    import json
    
    # Buscar o último mês disponível na tabela receita_itens
    uid = _current_user_id()
    if not uid:
        current_app.logger.warning("RECEITA_PASSIVA: Sem user_id válido")
        return 0.0
    
    try:
        # Buscar o último mês com dados na tabela
        res_meses = (supabase.table("receita_itens")
                    .select("data_ref")
                    .eq("user_id", uid)
                    .order("data_ref", desc=True)
                    .limit(1)
                    .execute())
        
        if not res_meses.data:
            current_app.logger.info("RECEITA_PASSIVA: Nenhum dado na tabela receita_itens")
            return 0.0
        
        ultimo_mes_disponivel = res_meses.data[0].get("data_ref", "")
        if not ultimo_mes_disponivel:
            current_app.logger.warning("RECEITA_PASSIVA: data_ref vazia")
            return 0.0
        
        # Extrair YYYY-MM do último mês
        mes_target = ultimo_mes_disponivel[:7]  # YYYY-MM
        
        current_app.logger.info("RECEITA_PASSIVA: Último mês disponível na tabela: %s (de data_ref: %s)", 
                               mes_target, ultimo_mes_disponivel)
        
        # Buscar categorias salvas nas preferências do usuário
        # Usando mesma lógica da receita.py para compatibilidade
        user_session = session.get("user", {})
        user_key = (user_session.get("email") or user_session.get("nome") or "anon").strip().lower()

        # Usar a mesma lógica da tela de Receita: primeiro por user_key, depois por user_id
        res_prefs = (supabase.table("user_prefs")
                    .select("value")
                    .eq("user_key", user_key)
                    .eq("key", "recorrencia_produtos")
                    .eq("user_id", uid)
                    .limit(1)
                    .execute())

        # Fallback para buscar apenas por user_id se não encontrar com user_key
        if not res_prefs.data:
            current_app.logger.info("RECEITA_PASSIVA: Tentando fallback sem user_key")
            res_prefs = (supabase.table("user_prefs")
                        .select("value")
                        .eq("user_id", uid)
                        .eq("key", "recorrencia_produtos")
                        .limit(1)
                        .execute())
        
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
        
        current_app.logger.info("RECEITA_PASSIVA: Produtos selecionados: %s (%d produtos)", list(selected_set), len(selected_set))
        
        # Buscar receitas do último mês disponível
        try:
            # Buscar receitas do mês target encontrado
            res_receitas = (supabase.table("receita_itens")
                          .select("valor_liquido, produto, familia")
                          .eq("user_id", uid)
                          .like("data_ref", f"{mes_target}%")
                          .execute())
            
            current_app.logger.info("RECEITA_PASSIVA: Encontradas %d receitas no mês %s", 
                                   len(res_receitas.data or []), mes_target)
            
            total_passiva = 0.0
            
            for receita in res_receitas.data or []:
                produto = (receita.get("produto") or "").strip()
                familia = (receita.get("familia") or "").strip()
                val_liq = _to_float(receita.get("valor_liquido"))
                
                # Lógica similar à tela de receita (linhas 279-282 de receita.py)
                produto_presente = bool(produto)
                
                # Verificar se família é administrativa (ignorar)
                def _is_admin_family(fam):
                    fam_lower = fam.lower()
                    return any(x in fam_lower for x in ["admin", "corretagem", "custódia", "escritório"])
                
                if _is_admin_family(familia):
                    continue  # Ignorar famílias administrativas
                
                # Regra da receita recorrente:
                if not produto_presente:
                    # Se não tem produto, conta como recorrente
                    total_passiva += val_liq
                    current_app.logger.debug("RECEITA_PASSIVA: +%.2f (sem produto)", val_liq)
                else:
                    # Se tem produto, só conta se estiver nas categorias selecionadas
                    if not selected_set or (produto in selected_set):
                        total_passiva += val_liq
                        current_app.logger.debug("RECEITA_PASSIVA: +%.2f de produto %s", val_liq, produto)
        
        except Exception as e:
            current_app.logger.error("RECEITA_PASSIVA: Erro ao buscar receitas: %s", e)
            return 0.0
        
        current_app.logger.info("RECEITA_PASSIVA: Total recorrente calculado: %.2f (mês %s)", total_passiva, mes_target)
        return total_passiva
        
    except Exception as e:
        current_app.logger.error("RECEITA_PASSIVA: Erro geral: %s", e)
        return 0.0


def _receita_escritorio_recorrente(clientes) -> float:
    """
    Calcula a receita ESCRITÓRIO recorrente baseada na receita assessor recorrente.
    Fórmula: Receita Escritório = Receita Assessor ÷ 80% ÷ Média Ponderada
    """
    receita_assessor_rec = _receita_assessor_recorrente()

    current_app.logger.info("RECEITA_ESCRIT_REC: Receita assessor recorrente = %.2f", receita_assessor_rec)

    if receita_assessor_rec <= 0:
        current_app.logger.warning("RECEITA_ESCRIT_REC: Receita assessor recorrente = 0, retornando 0. Verifique se há dados na tabela receita_itens e produtos configurados como recorrentes.")
        return 0.0

    if not clientes:
        current_app.logger.warning("RECEITA_ESCRIT_REC: Sem clientes para calcular média ponderada")
        return 0.0

    # Verificar se campo repasse existe nos clientes
    if 'repasse' not in clientes[0]:
        current_app.logger.error("RECEITA_ESCRIT_REC: Campo 'repasse' não encontrado nos clientes! Campos disponíveis: %s",
                                list(clientes[0].keys()) if clientes else [])
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
                    current_app.logger.info("RECEITA_ESCRIT_REC: Cliente %d: %s - NET=%.2f, repasse=%.2f%%, ponderado=%.2f",
                                           i+1, nome, net_total, repasse, ponderado_cliente)

    current_app.logger.info("RECEITA_ESCRIT_REC: %d clientes total, %d com NET>0, %d com repasse>0",
                           len(clientes), clientes_com_net, clientes_com_repasse)
    current_app.logger.info("RECEITA_ESCRIT_REC: total_net=%.2f, total_net_ponderado=%.2f",
                           total_net, total_net_ponderado)

    if total_net == 0:
        current_app.logger.warning("RECEITA_ESCRIT_REC: Nenhum cliente com NET > 0")
        return 0.0

    if total_net_ponderado == 0:
        current_app.logger.warning("RECEITA_ESCRIT_REC: Total NET ponderado = 0. Verifique se os clientes têm repasse configurado.")
        return 0.0

    media_ponderada_repasse = total_net_ponderado / total_net

    # Fórmula inversa: Receita Escritório = Receita Assessor ÷ 80% ÷ Média Ponderada
    receita_escritorio_rec = receita_assessor_rec / 0.80 / media_ponderada_repasse

    current_app.logger.info("RECEITA_ESCRIT_REC: Média ponderada: %.4f (%.2f%%) | Resultado: %.2f ÷ 80%% ÷ %.4f = %.2f",
                           media_ponderada_repasse, media_ponderada_repasse * 100,
                           receita_assessor_rec, media_ponderada_repasse, receita_escritorio_rec)

    return receita_escritorio_rec


def _receita_escritorio_total_mes(clientes):
    """
    Calcula a receita total do escritório no mês atual:
    Receita Ativa (alocações EFETIVADAS) + Receita Recorrente (calculada a partir da receita assessor) + Bônus
    """
    receita_ativa = _receita_escritorio_mes_atual_via_alocacoes()
    receita_recorrente = _receita_escritorio_recorrente(clientes)
    bonus_ativo = _carregar_bonus_ativo_mes()

    total = receita_ativa + receita_recorrente + bonus_ativo

    current_app.logger.info("RECEITA_ESCRIT_TOTAL: Ativa=%.2f (alocações) + Recorrente=%.2f + Bônus=%.2f = Total=%.2f",
                           receita_ativa, receita_recorrente, bonus_ativo, total)

    return total


def _receita_assessor_mes(receita_escritorio: float, clientes) -> float:
    """
    Calcula a receita do assessor no mês usando a fórmula:
    Receita Assessor = Receita Escritório × 80% × (Média Ponderada do NET × Repasse)

    Média Ponderada = Σ(NET_cliente × Repasse_cliente) / Σ(NET_cliente)
    """
    current_app.logger.info("RECEITA_ASSESSOR: Iniciando cálculo - Receita Escritório: %.2f, Clientes: %d",
                           receita_escritorio, len(clientes) if clientes else 0)

    if not clientes:
        current_app.logger.warning("RECEITA_ASSESSOR: Lista de clientes vazia")
        return 0.0

    if receita_escritorio <= 0:
        current_app.logger.warning("RECEITA_ASSESSOR: Receita escritório <= 0: %.2f", receita_escritorio)
        return 0.0

    total_net = 0.0
    total_net_ponderado = 0.0
    clientes_validos = 0
    clientes_sem_repasse = 0

    # Verificar se campo repasse existe nos clientes
    if clientes and 'repasse' not in clientes[0]:
        current_app.logger.error("RECEITA_ASSESSOR: Campo 'repasse' não encontrado nos clientes! Campos disponíveis: %s",
                                list(clientes[0].keys()) if clientes else [])
        return 0.0

    for i, cliente in enumerate(clientes):
        nome = cliente.get("nome", "Sem nome")[:30]  # Primeiros 30 chars
        net_total = _to_float(cliente.get("net_total"))
        repasse = _to_float(cliente.get("repasse"))

        # Debug apenas dos primeiros 5 clientes para não poluir log
        if i < 5:
            current_app.logger.info("RECEITA_ASSESSOR: Cliente %d: %s | NET: %.2f | Repasse: %.2f%%",
                                   i+1, nome, net_total, repasse)

        # Só considerar clientes com NET > 0
        if net_total > 0:
            clientes_validos += 1
            total_net += net_total

            if repasse > 0:
                contribution = net_total * repasse / 100.0
                total_net_ponderado += contribution

                if i < 5:
                    current_app.logger.info("  ✅ Válido | Contribuição: %.2f × %.2f%% = %.2f",
                                           net_total, repasse, contribution)
            else:
                clientes_sem_repasse += 1
                if i < 5:
                    current_app.logger.info("  ⚠️  NET válido mas repasse = 0")
        else:
            if i < 5:
                current_app.logger.info("  ❌ Ignorado (NET <= 0)")

    current_app.logger.info("RECEITA_ASSESSOR: %d clientes válidos (NET>0), %d sem repasse configurado",
                           clientes_validos, clientes_sem_repasse)
    current_app.logger.info("RECEITA_ASSESSOR: Total NET: %.2f, Total NET ponderado: %.2f",
                           total_net, total_net_ponderado)

    if total_net == 0:
        current_app.logger.warning("RECEITA_ASSESSOR: Nenhum cliente com NET > 0")
        return 0.0

    if total_net_ponderado == 0:
        current_app.logger.warning("RECEITA_ASSESSOR: Total NET ponderado = 0. Verifique se os clientes têm repasse configurado.")
        return 0.0

    # Calcular média ponderada do repasse
    media_ponderada_repasse = total_net_ponderado / total_net

    # Fórmula final
    receita_assessor_base = receita_escritorio * 0.80 * media_ponderada_repasse

    # Adicionar bônus ativos do mês
    bonus_ativo = _carregar_bonus_ativo_mes()
    receita_assessor = receita_assessor_base + bonus_ativo

    current_app.logger.info("RECEITA_ASSESSOR: Média ponderada: %.4f (%.2f%%) | Base: %.2f × 80%% × %.4f = %.2f",
                           media_ponderada_repasse, media_ponderada_repasse * 100,
                           receita_escritorio, media_ponderada_repasse, receita_assessor_base)
    current_app.logger.info("RECEITA_ASSESSOR: Bônus ativo: R$ %.2f | Receita total: R$ %.2f",
                           bonus_ativo, receita_assessor)

    return receita_assessor


def _calcular_roa(receita_escritorio_mes: float, clientes) -> float:
    """
    Calcula o ROA (Return on Assets) em percentual.
    Fórmula: ROA = (Receita Escritório Mês × 12) ÷ Soma NET Total × 100%
    """
    if not clientes or receita_escritorio_mes <= 0:
        current_app.logger.info("ROA: Receita escritório=%.2f ou sem clientes", receita_escritorio_mes)
        return 0.0
    
    # Somar NET total de todos os clientes
    soma_net_total = 0.0
    clientes_com_net = 0
    
    for cliente in clientes:
        net_total = _to_float(cliente.get("net_total"))
        if net_total > 0:  # Só contar clientes com NET > 0
            soma_net_total += net_total
            clientes_com_net += 1
    
    if soma_net_total == 0:
        current_app.logger.warning("ROA: Soma NET total = 0")
        return 0.0
    
    # Fórmula: (Receita × 12) ÷ NET Total × 100
    receita_anualizada = receita_escritorio_mes * 12
    roa_decimal = receita_anualizada / soma_net_total
    roa_percentual = roa_decimal * 100
    
    current_app.logger.info("ROA: (%.2f × 12) ÷ %.2f = %.4f = %.2f%%", 
                           receita_escritorio_mes, soma_net_total, roa_decimal, roa_percentual)
    current_app.logger.info("ROA: Baseado em %d clientes com NET > 0", clientes_com_net)
    
    return roa_percentual



def _historico_receita_passiva_assessor() -> list:
    """
    Busca o histórico da receita passiva (assessor) mês a mês.
    Retorna lista de dicionários: [{"mes": "2025-01", "valor": 1500.0}, ...]
    """
    current_app.logger.info("HIST_RECEITA_PASSIVA: INICIANDO função")

    supabase = _get_supabase()
    if not supabase:
        current_app.logger.info("HIST_RECEITA_PASSIVA: Supabase não disponível")
        return []
    
    import json
    from collections import defaultdict
    
    uid = _current_user_id()
    current_app.logger.info("HIST_RECEITA_PASSIVA: User ID: %s", uid)
    if not uid:
        current_app.logger.info("HIST_RECEITA_PASSIVA: Sem user_id")
        return []
    
    try:
        # Buscar TODAS as receitas do usuário com paginação
        all_receitas = []
        page_size = 1000
        # 🚀 OTIMIZAÇÃO: Limitar busca aos últimos 24 meses (reduz volume drasticamente)
        from datetime import datetime, timedelta
        hoje = datetime.now()
        data_limite = (hoje - timedelta(days=730)).strftime('%Y-%m')  # 24 meses atrás

        offset = 0
        max_iterations = 50  # Segurança: máximo 50 páginas (50k registros)
        iterations = 0

        while iterations < max_iterations:
            res_receitas = (supabase.table("receita_itens")
                          .select("data_ref, valor_liquido, produto, familia")
                          .eq("user_id", uid)
                          .gte("data_ref", data_limite)  # 🚀 FILTRO: apenas últimos 24 meses
                          .order("id")
                          .range(offset, offset + page_size - 1)
                          .execute())

            if not res_receitas.data:
                break

            all_receitas.extend(res_receitas.data)
            current_app.logger.info("HIST_RECEITA_PASSIVA: Página offset %d - %d registros", offset, len(res_receitas.data))

            # Se a página retornou menos que page_size, é a última página
            if len(res_receitas.data) < page_size:
                break

            offset += page_size
            iterations += 1
        
        current_app.logger.info("HIST_RECEITA_PASSIVA: TOTAL de receitas encontradas: %d", len(all_receitas))
        
        if not all_receitas:
            current_app.logger.info("HIST_RECEITA_PASSIVA: Nenhuma receita encontrada")
            return []
        
        # Buscar categorias selecionadas - mesma lógica
        user_session = session.get("user", {})
        user_key = (user_session.get("email") or user_session.get("nome") or "anon").strip().lower()

        res_prefs = (supabase.table("user_prefs")
                    .select("value")
                    .eq("user_id", uid)
                    .eq("user_key", user_key)
                    .eq("key", "recorrencia_produtos")
                    .limit(1)
                    .execute())

        # Fallback sem user_key
        if not res_prefs.data:
            res_prefs = (supabase.table("user_prefs")
                        .select("value")
                        .eq("user_id", uid)
                        .eq("key", "recorrencia_produtos")
                        .limit(1)
                        .execute())
        
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
        
        current_app.logger.info("HIST_RECEITA_PASSIVA: Produtos selecionados: %s", list(selected_set))
        
        # Agrupar por mês
        receita_por_mes = defaultdict(float)
        total_processados = 0
        total_incluidos = 0
        
        for receita in all_receitas:
            total_processados += 1
            data_ref = receita.get("data_ref", "")
            if not data_ref:
                continue
                
            mes = data_ref[:7]  # YYYY-MM
            produto = (receita.get("produto") or "").strip()
            familia = (receita.get("familia") or "").strip()
            val_liq = _to_float(receita.get("valor_liquido"))
            
            # Aplicar mesma lógica da receita passiva
            def _is_admin_family(fam):
                fam_lower = fam.lower()
                return any(x in fam_lower for x in ["admin", "corretagem", "custódia", "escritório"])
            
            is_admin = _is_admin_family(familia)
            if is_admin:
                if total_processados <= 5:
                    current_app.logger.info("HIST_RECEITA_PASSIVA: Registro %d IGNORADO (admin) - Mês: %s, Família: '%s', Produto: '%s', Valor: %s", 
                                           total_processados, mes, familia, produto, val_liq)
                continue  # Ignorar famílias administrativas
            
            # Regra da receita recorrente
            produto_presente = bool(produto)
            incluir = False
            
            if not produto_presente:
                # Se não tem produto, conta como recorrente
                receita_por_mes[mes] += val_liq
                incluir = True
                total_incluidos += 1
            else:
                # Se tem produto, só conta se estiver nas categorias selecionadas
                if not selected_set or (produto in selected_set):
                    receita_por_mes[mes] += val_liq
                    incluir = True
                    total_incluidos += 1
            
            if total_processados <= 10:  # Log dos primeiros 10 registros
                current_app.logger.info("HIST_RECEITA_PASSIVA: Registro %d - Mês: %s, Família: '%s', Produto: '%s', Valor: %s, Incluído: %s", 
                                       total_processados, mes, familia, produto, val_liq, incluir)
        
        current_app.logger.info("HIST_RECEITA_PASSIVA: Processados %d registros, incluídos %d", total_processados, total_incluidos)
        
        # Converter para lista ordenada
        historico = []
        for mes in sorted(receita_por_mes.keys()):
            historico.append({
                "mes": mes,
                "receita": receita_por_mes[mes]
            })
        
        current_app.logger.info("HIST_RECEITA_PASSIVA: %d meses processados", len(historico))
        current_app.logger.info("HIST_RECEITA_PASSIVA: Dados finais: %s", historico)
        return historico
        
    except Exception as e:
        current_app.logger.error("HIST_RECEITA_PASSIVA: Erro: %s", e)
        return []


def _penetracao_base_xp_mb_mes(clientes) -> tuple[tuple[float, int, int], tuple[float, int, int]]:
    """
    % Penetração de base no mês vigente, separada entre XP e MB.

    Penetração XP: Cliente é considerado XP se tem qualquer alocação que NÃO seja Renda Fixa Digital
    Penetração MB: Cliente é considerado MB APENAS se tem SOMENTE alocações de Renda Fixa Digital

    Regra importante: cliente alocado deve ser considerado apenas uma vez.
    Se cliente tem XP E MB, ele é considerado na Penetração XP.

    Returns:
        tuple: ((xp_pct, xp_numerador, xp_denominador), (mb_pct, mb_numerador, mb_denominador))
    """
    supabase = _get_supabase()
    if not supabase:
        return (0.0, 0, 0), (0.0, 0, 0)

    def _is_yes(v) -> bool:
        s = str(v or "").strip().lower()
        return s in {"sim", "s", "true", "1", "yes", "y"}

    mes_atual = datetime.today().strftime("%Y-%m")

    # ---- Denominador: clientes com NET>0 (já vêm filtrados por user) ----
    base_ids = {c["id"] for c in clientes if _to_float(c.get("net_total")) > 0}
    denominador = len(base_ids)
    if denominador == 0:
        return (0.0, 0, 0), (0.0, 0, 0)

    # ---- Lê alocações do usuário, com embed do PRODUTO e flag EFETIVADA ----
    try:
        q = supabase.table("alocacoes").select(
            "cliente_id, created_at, efetivada, produto:produto_id ( em_campanha, campanha_mes, classe )"
        )
        q = _with_user(q)
        res = q.execute()
        rows = list(res.data or [])
    except Exception as e:
        current_app.logger.info("dashboard: falha ao buscar alocacoes p/ penetração XP/MB (%s)", e)
        rows = []

    # ---- Analisar alocações e classificar clientes ----
    clientes_xp = set()  # Clientes que têm pelo menos uma alocação não-RFD
    clientes_mb = set()  # Clientes que têm APENAS alocações RFD
    clientes_com_rfd = set()  # Clientes que têm alocações RFD
    clientes_com_nao_rfd = set()  # Clientes que têm alocações não-RFD

    debug_count = 0

    for r in rows:
        debug_count += 1
        created_ym = (r.get("created_at") or "")[:7]

        # Debug dos primeiros 5 registros
        if debug_count <= 5:
            produto = r.get("produto") or {}
            current_app.logger.info("PENETRACAO_XP_MB_DEBUG %d: created=%s, mes_atual=%s, em_campanha=%s, efetivada=%s, cliente_id=%s, classe=%s",
                                   debug_count, created_ym, mes_atual,
                                   produto.get("em_campanha"), r.get("efetivada"), r.get("cliente_id"), produto.get("classe"))

        if created_ym != mes_atual:
            continue

        produto = r.get("produto") or {}
        em_campanha = produto.get("em_campanha")
        if not _is_yes(em_campanha):
            if debug_count <= 5:
                current_app.logger.info("PENETRACAO_XP_MB_DEBUG %d: Rejeitado por em_campanha=%s", debug_count, em_campanha)
            continue

        efetivada = r.get("efetivada")
        if not _is_yes(efetivada) and not bool(efetivada):
            if debug_count <= 5:
                current_app.logger.info("PENETRACAO_XP_MB_DEBUG %d: Rejeitado por efetivada=%s", debug_count, efetivada)
            continue

        cid = r.get("cliente_id")
        if cid not in base_ids:
            continue

        # Verificar se é Renda Fixa Digital
        classe = (produto.get("classe") or "").strip().upper()
        is_renda_fixa_digital = classe == "RENDA FIXA DIGITAL"

        if is_renda_fixa_digital:
            clientes_com_rfd.add(cid)
            if debug_count <= 5:
                current_app.logger.info("PENETRACAO_XP_MB_DEBUG %d: Cliente %s marcado como RFD", debug_count, cid)
        else:
            clientes_com_nao_rfd.add(cid)
            if debug_count <= 5:
                current_app.logger.info("PENETRACAO_XP_MB_DEBUG %d: Cliente %s marcado como NÃO-RFD (classe: %s)", debug_count, cid, classe)

    # ---- Aplicar regras de classificação ----
    # XP: Qualquer cliente que tenha pelo menos uma alocação não-RFD
    clientes_xp = clientes_com_nao_rfd.copy()

    # MB: Apenas clientes que têm SOMENTE alocações RFD (e não têm nenhuma não-RFD)
    clientes_mb = clientes_com_rfd - clientes_com_nao_rfd

    xp_numerador = len(clientes_xp)
    mb_numerador = len(clientes_mb)

    xp_pct = (xp_numerador / denominador * 100.0) if denominador else 0.0
    mb_pct = (mb_numerador / denominador * 100.0) if denominador else 0.0

    current_app.logger.info("PENETRACAO_XP_MB: Base clientes (NET>0): %d", denominador)
    current_app.logger.info("PENETRACAO_XP_MB: Alocações analisadas: %d", len(rows))
    current_app.logger.info("PENETRACAO_XP_MB: Clientes com RFD: %d", len(clientes_com_rfd))
    current_app.logger.info("PENETRACAO_XP_MB: Clientes com não-RFD: %d", len(clientes_com_nao_rfd))
    current_app.logger.info("PENETRACAO_XP_MB: Clientes XP (com pelo menos uma não-RFD): %d", xp_numerador)
    current_app.logger.info("PENETRACAO_XP_MB: Clientes MB (apenas RFD): %d", mb_numerador)
    current_app.logger.info("PENETRACAO_XP_MB: XP: %.2f%% (%d/%d)", xp_pct, xp_numerador, denominador)
    current_app.logger.info("PENETRACAO_XP_MB: MB: %.2f%% (%d/%d)", mb_pct, mb_numerador, denominador)

    return (xp_pct, xp_numerador, denominador), (mb_pct, mb_numerador, denominador)


def _penetracao_base_mes(clientes) -> tuple[float, int, int]:
    """
    % Penetração de base no mês vigente (função mantida para compatibilidade).
    Numerador: nº de clientes (únicos) que têm pelo menos 1 alocação
               EFETIVADA e com produto.em_campanha = 'Sim'/true no mês vigente.
    Denominador: nº de clientes com NET > 0.
    """
    supabase = _get_supabase()
    if not supabase:
        return 0.0, 0, 0

    def _is_yes(v) -> bool:
        s = str(v or "").strip().lower()
        return s in {"sim", "s", "true", "1", "yes", "y"}

    mes_atual = datetime.today().strftime("%Y-%m")

    # ---- Denominador: clientes com NET>0 (já vêm filtrados por user) ----
    base_ids = {c["id"] for c in clientes if _to_float(c.get("net_total")) > 0}
    denominador = len(base_ids)
    if denominador == 0:
        return 0.0, 0, 0

    # ---- Lê alocações do usuário, com embed do PRODUTO e flag EFETIVADA ----
    try:
        q = supabase.table("alocacoes").select(
            "cliente_id, created_at, efetivada, produto:produto_id ( em_campanha, campanha_mes )"
        )
        q = _with_user(q)
        res = q.execute()
        rows = list(res.data or [])
    except Exception as e:
        current_app.logger.info("dashboard: falha ao buscar alocacoes p/ penetração (%s)", e)
        rows = []

    # ---- Numerador: únicos no mês, campanha=Sim e efetivada=Sim ----
    clientes_com_aloc = set()
    debug_count = 0

    for r in rows:
        debug_count += 1
        created_ym = (r.get("created_at") or "")[:7]

        # Debug dos primeiros 5 registros
        if debug_count <= 5:
            produto = r.get("produto") or {}
            current_app.logger.info("PENETRACAO_DEBUG %d: created=%s, mes_atual=%s, em_campanha=%s, efetivada=%s, cliente_id=%s",
                                   debug_count, created_ym, mes_atual,
                                   produto.get("em_campanha"), r.get("efetivada"), r.get("cliente_id"))

        if created_ym != mes_atual:
            continue

        produto = r.get("produto") or {}
        em_campanha = produto.get("em_campanha")
        if not _is_yes(em_campanha):
            if debug_count <= 5:
                current_app.logger.info("PENETRACAO_DEBUG %d: Rejeitado por em_campanha=%s", debug_count, em_campanha)
            continue

        efetivada = r.get("efetivada")
        if not _is_yes(efetivada) and not bool(efetivada):
            if debug_count <= 5:
                current_app.logger.info("PENETRACAO_DEBUG %d: Rejeitado por efetivada=%s", debug_count, efetivada)
            continue

        cid = r.get("cliente_id")
        if cid in base_ids:
            clientes_com_aloc.add(cid)
            if debug_count <= 5:
                current_app.logger.info("PENETRACAO_DEBUG %d: ACEITO - cliente_id=%s", debug_count, cid)

    numerador = len(clientes_com_aloc)
    pct = (numerador / denominador * 100.0) if denominador else 0.0

    current_app.logger.info("PENETRACAO_BASE: Base clientes (NET>0): %d", denominador)
    current_app.logger.info("PENETRACAO_BASE: Alocações analisadas: %d", len(rows))
    current_app.logger.info("PENETRACAO_BASE: Clientes com alocação válida: %d", numerador)
    current_app.logger.info("PENETRACAO_BASE: Percentual: %.2f%% (%d/%d)", pct, numerador, denominador)

    current_app.logger.info(
        "[PENETRACAO] mes=%s ativos=%s base=%s pct=%.2f (produto.em_campanha=Sim & efetivada=Sim)",
        mes_atual, numerador, denominador, pct
    )
    return pct, numerador, denominador


# --------------- view ---------------
@dash_bp.route("/debug", methods=["GET"])
@login_required
def debug():
    """Debug completo: sessão, autenticação, metas"""
    supabase = _get_supabase()
    uid = _current_user_id()
    mes_atual = datetime.today().strftime("%Y-%m")

    # Info básica
    debug_info = {
        "user_id": uid,
        "session_user_keys": list(session.get("user", {}).keys()),
        "session_access_token": bool(session.get("user", {}).get("access_token")),
        "supabase_available": supabase is not None,
        "mes_atual": mes_atual
    }
    
    # Teste cliente autenticado
    client_info = {}
    try:
        client = get_supabase_client()
        client_info["client_type"] = "autenticado" if hasattr(client, 'auth') else "admin"
        
        # Testa auth do cliente
        try:
            user_resp = client.auth.get_user()
            client_info["auth_user_id"] = user_resp.user.id if user_resp.user else None
        except Exception as e:
            client_info["auth_error"] = str(e)
            
    except Exception as e:
        client_info["client_error"] = str(e)
    
    # Testa metas
    metas_info = {}
    try:
        # Com cliente autenticado
        client = get_supabase_client()
        res_auth = client.table("metas_mensais").select("*").eq("mes", mes_atual).execute()
        metas_info["metas_cliente_auth"] = list(res_auth.data or [])
        
        # SEGURANÇA: Não buscar TODAS as metas (vazamento de dados)
        metas_info["metas_admin_todas"] = "CONSULTA_REMOVIDA_POR_SEGURANCA"
        
        if uid:
            # SEGURANÇA: Usar cliente autenticado em vez de admin
            auth_client = _get_supabase()
            if auth_client:
                res_auth_filter = auth_client.table("metas_mensais").select("*").eq("user_id", uid).execute()
                metas_info["metas_auth_filtradas"] = list(res_auth_filter.data or [])
            else:
                metas_info["metas_auth_filtradas"] = "ACESSO_NEGADO_SEM_CLIENTE_AUTENTICADO"
            
    except Exception as e:
        metas_info["metas_error"] = str(e)
    
    debug_info.update({
        "client_info": client_info,
        "metas_info": metas_info
    })
    
    return f"<pre>{debug_info}</pre>"

def _calcular_metricas_dashboard():
    """
    Calcula todas as métricas do dashboard de uma vez para otimizar performance.
    Esta função é cacheada para evitar recálculos desnecessários.
    """
    mes, meta = _meta_do_mes()
    clientes = _fetch_clientes_otimizado()

    # Verificar se os clientes têm todos os campos necessários para cálculos
    if clientes:
        primeiro_cliente = clientes[0]
        campos_necessarios = ['id', 'nome', 'net_total', 'repasse', 'codigo_xp', 'codigo_mb']
        campos_faltando = [campo for campo in campos_necessarios if campo not in primeiro_cliente]

        if campos_faltando:
            current_app.logger.warning("DASHBOARD_METRICS: Campos faltando em _fetch_clientes_otimizado: %s. Usando _fetch_clientes como fallback.", campos_faltando)
            clientes = _fetch_clientes()
        else:
            current_app.logger.info("DASHBOARD_METRICS: Todos os campos necessários presentes em _fetch_clientes_otimizado")
    else:
        current_app.logger.warning("DASHBOARD_METRICS: Nenhum cliente retornado por _fetch_clientes_otimizado. Usando _fetch_clientes como fallback.")
        clientes = _fetch_clientes()

    # Calcular receita total do escritório (ativa + recorrente + bônus)
    receita_ativa_mes = float(_receita_escritorio_mes_atual_via_alocacoes() or 0.0)
    receita_recorrente_mes_pura = float(_receita_escritorio_recorrente(clientes) or 0.0)
    bonus_ativo_mes = _carregar_bonus_ativo_mes()
    receita_total_mes = receita_ativa_mes + receita_recorrente_mes_pura + bonus_ativo_mes

    # Calcular receita do assessor usando a fórmula original (já inclui bônus)
    receita_assessor_mes = _receita_assessor_mes(receita_total_mes, clientes)

    # Calcular receita assessor esperada baseada na meta
    receita_assessor_esperada = _receita_assessor_esperada(meta, clientes)

    # Calcular ROA
    roa_percentual = _calcular_roa(receita_total_mes, clientes)

    # Buscar histórico da receita passiva
    historico_receita_passiva = _historico_receita_passiva_assessor()


    by_modelo = _net_by_modelo(clientes)
    mediana_net = _median([c.get("net_total") for c in clientes if _to_float(c.get("net_total")) > 0])

    totais_receita_by_id, mediana_receita_ytd = _receita_ytd_por_cliente(clientes)

    # ---- % Penetração de base (Campanha=Sim e Efetivada=Sim) ----
    penetracao_pct, penetracao_ativos, penetracao_base = _penetracao_base_mes(clientes)

    # ---- % Penetração separada XP e MB ----
    (xp_pct, xp_numerador, xp_denominador), (mb_pct, mb_numerador, mb_denominador) = _penetracao_base_xp_mb_mes(clientes)

    # ---- % Penetração total (XP + MB) ----
    # Numerador: XP + MB (sem duplicação, pois XP já exclui quem está em MB)
    total_numerador = xp_numerador + mb_numerador
    total_denominador = xp_denominador  # Mesmo denominador (clientes com NET > 0)
    total_pct = (total_numerador / total_denominador * 100.0) if total_denominador else 0.0

    # Debug: log das métricas calculadas
    current_app.logger.info("DASHBOARD_DEBUG: Clientes carregados: %d", len(clientes))
    current_app.logger.info("DASHBOARD_DEBUG: Receita total mês: %.2f", receita_total_mes)
    current_app.logger.info("DASHBOARD_DEBUG: Receita assessor mês: %.2f", receita_assessor_mes)
    current_app.logger.info("DASHBOARD_DEBUG: Receita assessor esperada: %.2f", receita_assessor_esperada)
    current_app.logger.info("DASHBOARD_DEBUG: ROA percentual: %.2f", roa_percentual)
    current_app.logger.info("DASHBOARD_DEBUG: Mediana NET: %.2f", mediana_net)
    current_app.logger.info("DASHBOARD_DEBUG: Mediana receita YTD: %.2f", mediana_receita_ytd)
    current_app.logger.info("DASHBOARD_DEBUG: Penetração: %.2f%% (%d/%d)", penetracao_pct, penetracao_ativos, penetracao_base)

    # Adicionar timestamp para debug de cache
    import time
    result = {
        'mes': mes,
        'meta': meta,
        'clientes': clientes,
        'receita_total_mes': receita_total_mes,
        'receita_ativa_mes': receita_ativa_mes,
        'receita_recorrente_mes': receita_recorrente_mes_pura,
        'bonus_ativo_mes': bonus_ativo_mes,
        'receita_assessor_mes': receita_assessor_mes,
        'receita_assessor_esperada': receita_assessor_esperada,
        'roa_percentual': roa_percentual,
        'historico_receita_passiva': historico_receita_passiva,
        'by_modelo': by_modelo,
        'mediana_net': mediana_net,
        'totais_receita_by_id': totais_receita_by_id,
        'mediana_receita_ytd': mediana_receita_ytd,
        'penetracao_pct': penetracao_pct,
        'penetracao_ativos': penetracao_ativos,
        'penetracao_base': penetracao_base,
        # Penetração separada XP e MB
        'xp_pct': xp_pct,
        'xp_numerador': xp_numerador,
        'xp_denominador': xp_denominador,
        'mb_pct': mb_pct,
        'mb_numerador': mb_numerador,
        'mb_denominador': mb_denominador,
        # Penetração total (XP + MB)
        'total_pct': total_pct,
        'total_numerador': total_numerador,
        'total_denominador': total_denominador,
        '_cached_at': time.time()  # Para debug
    }

    current_app.logger.info("DASHBOARD_METRICS: Calculado em %.2fs", time.time() - result['_cached_at'])
    return result

def invalidar_cache_dashboard():
    """
    Invalida todos os caches relacionados ao dashboard.
    Deve ser chamada quando dados relevantes são alterados.
    """
    try:
        invalidate_user_cache('dashboard_metrics')
        invalidate_user_cache('dashboard_clientes_otimizado')
        invalidate_user_cache('dashboard_data')  # Cache original
        invalidate_user_cache('receita_ytd_por_cliente')
        invalidate_user_cache('receita_escritorio_total_mes')
        invalidate_user_cache('historico_receita_passiva')
        invalidate_user_cache('penetracao_base_mes')
        current_app.logger.info("CACHE: Dashboard cache invalidado com sucesso")
    except Exception as e:
        current_app.logger.error("CACHE: Erro ao invalidar cache do dashboard: %s", e)

def invalidar_cache_dashboard_forcado():
    """
    Força invalidação completa de cache, incluindo caches que podem estar corrompidos.
    """
    from cache_manager import invalidate_user_cache

    caches_para_limpar = [
        'dashboard_metrics',
        'dashboard_clientes_otimizado',
        'dashboard_data',
        'receita_ytd_por_cliente',
        'receita_escritorio_total_mes',
        'historico_receita_passiva',
        'penetracao_base_mes',
        'clientes_list',
        'produtos_list',
        'alocacoes_receitas'
    ]

    current_app.logger.info("CACHE_FORCADO: Invalidando %d tipos de cache", len(caches_para_limpar))

    for cache_key in caches_para_limpar:
        try:
            invalidate_user_cache(cache_key)
            current_app.logger.info("CACHE_FORCADO: Cache '%s' invalidado", cache_key)
        except Exception as e:
            current_app.logger.error("CACHE_FORCADO: Erro ao invalidar cache '%s': %s", cache_key, e)

@dash_bp.route("/", methods=["GET"])
@login_required
def index():
    # Usar função otimizada com cache para calcular todas as métricas
    metricas = _calcular_metricas_dashboard()

    # Extrair dados da função cacheada
    mes = metricas['mes']
    meta = metricas['meta']
    clientes = metricas['clientes']
    receita_total_mes = metricas['receita_total_mes']
    receita_ativa_mes = metricas['receita_ativa_mes']
    receita_recorrente_mes = metricas['receita_recorrente_mes']
    receita_assessor_mes = metricas['receita_assessor_mes']
    receita_assessor_esperada = metricas['receita_assessor_esperada']
    roa_percentual = metricas['roa_percentual']
    historico_receita_passiva = metricas['historico_receita_passiva']
    by_modelo = metricas['by_modelo']
    net_by_modelo = by_modelo  # Manter compatibilidade
    mediana_net = metricas['mediana_net']
    totais_receita_by_id = metricas['totais_receita_by_id']
    mediana_receita_ytd = metricas['mediana_receita_ytd']
    penetracao_pct = metricas['penetracao_pct']
    penetracao_ativos = metricas['penetracao_ativos']
    penetracao_base = metricas['penetracao_base']
    # Penetração separada XP e MB
    xp_pct = metricas['xp_pct']
    xp_numerador = metricas['xp_numerador']
    xp_denominador = metricas['xp_denominador']
    mb_pct = metricas['mb_pct']
    mb_numerador = metricas['mb_numerador']
    mb_denominador = metricas['mb_denominador']
    # Penetração total
    total_pct = metricas['total_pct']
    total_numerador = metricas['total_numerador']
    total_denominador = metricas['total_denominador']

    pontos = []
    counts = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    clientes_por_quadrante = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    total_clientes = max(1, len(clientes))

    for c in clientes:
        cid = c.get("id")
        nome = (c.get("nome") or "").strip() or "Cliente"

        net = _to_float(c.get("net_total"))
        receita = _to_float(totais_receita_by_id.get(cid, 0.0))

        if receita >= mediana_receita_ytd and net >= mediana_net:
            quad = "Q1"; color = "#10b981"
        elif receita >= mediana_receita_ytd and net < mediana_net:
            quad = "Q2"; color = "#3b82f6"
        elif receita < mediana_receita_ytd and net >= mediana_net:
            quad = "Q3"; color = "#f59e0b"
        else:
            quad = "Q4"; color = "#94a3b8"

        counts[quad] += 1

        cliente_info = {
            "id": cid,
            "nome": nome,
            "modelo": (c.get("modelo") or "").strip() or "SEM_MODELO",
            "net_total": net,
            "receita_ano": receita,
            "codigo_xp": c.get("codigo_xp", ""),
            "codigo_mb": c.get("codigo_mb", "")
        }
        clientes_por_quadrante[quad].append(cliente_info)

        pontos.append({"x": receita, "y": net, "label": nome, "quadrant": quad, "color": color})

    quadrant_pct = {k: (counts[k] / total_clientes * 100.0) for k in counts.keys()}

    return render_template(
        "dashboard.html",
        mes=mes,
        meta=meta,
        receita_total=receita_total_mes,
        clientes=clientes,
        by_modelo=by_modelo,
        net_by_modelo=net_by_modelo,
        mediana_net=mediana_net,
        mediana_receita_escritorio_ano=mediana_receita_ytd,
        media_receita_escritorio_ano=mediana_receita_ytd,
        media_net=mediana_net,
        quadrant_points=pontos,
        quadrant_counts=counts,
        quadrant_pct=quadrant_pct,
        quadrant_total=total_clientes,
        clientes_por_quadrante=clientes_por_quadrante,
        # Card de penetração (original)
        penetracao_pct=penetracao_pct,
        penetracao_ativos=penetracao_ativos,
        penetracao_base=penetracao_base,
        # Cards de penetração separados XP e MB
        xp_pct=xp_pct,
        xp_numerador=xp_numerador,
        xp_denominador=xp_denominador,
        mb_pct=mb_pct,
        mb_numerador=mb_numerador,
        mb_denominador=mb_denominador,
        # Penetração total (XP + MB)
        total_pct=total_pct,
        total_numerador=total_numerador,
        total_denominador=total_denominador,
        # Detalhamento da receita (ativa + recorrente)
        receita_ativa_mes=receita_ativa_mes,
        receita_recorrente_mes=receita_recorrente_mes,
        receita_passiva_mes=_receita_assessor_recorrente(),
        # Receita do assessor
        receita_assessor_mes=receita_assessor_mes,
        # Receita assessor esperada (baseada na meta)
        receita_assessor_esperada=receita_assessor_esperada,
        # Receita assessor recorrente (para debug)
        receita_assessor_recorrente=_receita_assessor_recorrente(),
        # ROA
        roa_percentual=roa_percentual,
        # NET Total
        net_total_geral=sum(net_by_modelo.values()),
        # Histórico receita passiva para gráfico
        historico_receita_passiva=historico_receita_passiva,
    )
