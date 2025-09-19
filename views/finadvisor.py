# views/finadvisor.py
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from utils import login_required
from datetime import datetime
import re

try:
    from supabase_client import get_supabase_client
except Exception:
    get_supabase_client = None

def _get_supabase():
    """
    SEGURANÇA: Obtém cliente Supabase autenticado APENAS para o usuário atual.
    Retorna None se não há usuário válido para evitar vazamento de dados.
    """
    if not get_supabase_client:
        return None
    client = get_supabase_client()
    if client is None:
        current_app.logger.debug("FINADVISOR: Cliente Supabase não disponível (usuário não autenticado)")
    return client

fin_bp = Blueprint("finadvisor", __name__, url_prefix="/finadvisor")

# --------------------------- Helpers ---------------------------

def _uid():
    # Usar a mesma lógica do security_middleware
    from security_middleware import get_current_user_id
    return get_current_user_id()

def _raw_meta():
    """Une diferentes fontes de metadata dentro de session['user']."""
    u = session.get("user") or {}
    meta: dict = {}
    for key in ("raw_user_meta_data", "user_metadata", "app_metadata", "metadata"):
        v = u.get(key) or {}
        if isinstance(v, dict):
            meta.update(v)
    return meta

def _get_codigo_xp_from_meta() -> str:
    """
    Extrai codigo_xp de várias fontes e retorna apenas dígitos.
    Também aceita override por querystring (?codigo_xp=...).
    """
    arg = (request.args.get("codigo_xp") or "").strip()
    if arg:
        return _digits_only(arg)

    meta = _raw_meta()
    candidates = [
        meta.get("codigo_xp"), meta.get("xp_code"), meta.get("xp"),
        meta.get("codigoXP"), meta.get("codigo"),
    ]
    u = session.get("user") or {}
    candidates += [
        u.get("codigo_xp"), u.get("xp_code"), u.get("xp"),
        u.get("codigoXP"), u.get("codigo"),
    ]
    for c in candidates:
        if c:
            return _digits_only(str(c))
    return ""

def _digits_only(s: str) -> str:
    if not s:
        return ""
    return "".join(re.findall(r"\d+", str(s)))

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

# --- EM views/finadvisor.py ---

def _latest_month() -> str:
    """Mês mais recente existente em receita_itens (YYYY-MM) do usuário logado."""
    supabase = _get_supabase()
    if not supabase:
        return datetime.today().strftime("%Y-%m")
    try:
        uid = _uid()
        # Fail-closed: se não tiver uid válido, não olha a tabela toda
        if not uid:
            return datetime.today().strftime("%Y-%m")
        res = (
            supabase.table("receita_itens")
            .select("data_ref")
            .eq("user_id", uid)
            .order("data_ref", desc=True)
            .limit(1)
            .execute()
        )
        data = res.data or []
        if data:
            m = (data[0].get("data_ref") or "").strip()
            return m or datetime.today().strftime("%Y-%m")
    except Exception as e:
        current_app.logger.info("finadvisor._latest_month fallback: %s", e)
    return datetime.today().strftime("%Y-%m")


def _clientes_nome_map_by_xp() -> dict[str, str]:
    """Mapa codigo_xp (apenas dígitos) -> nome do cliente (somente do dono)."""
    mapa: dict[str, str] = {}
    supabase = _get_supabase()
    if not supabase:
        return mapa
    try:
        uid = _uid()
        if not uid:
            return mapa  # fail-closed
        q = supabase.table("clientes").select("codigo_xp,nome").eq("user_id", uid).range(0, 200000)
        res = q.execute()
        for r in (res.data or []):
            xp = _digits_only((r.get("codigo_xp") or "").strip())
            nm = (r.get("nome") or "").strip()
            if xp:
                mapa[xp] = nm or xp
    except Exception as e:
        current_app.logger.info("finadvisor: clientes map indisponível (%s)", e)
    return mapa


def _clientes_modelo_map_by_xp() -> dict[str, str]:
    """Mapa codigo_xp (apenas dígitos) -> modelo do cliente (somente do dono)."""
    mapa: dict[str, str] = {}
    supabase = _get_supabase()
    if not supabase:
        return mapa
    try:
        uid = _uid()
        if not uid:
            return mapa  # fail-closed
        q = supabase.table("clientes").select("codigo_xp,modelo").eq("user_id", uid).range(0, 200000)
        res = q.execute()
        for r in (res.data or []):
            xp = _digits_only((r.get("codigo_xp") or "").strip())
            md = (r.get("modelo") or "").strip().upper() or "TRADICIONAL"
            if xp:
                mapa[xp] = md
    except Exception as e:
        current_app.logger.info("finadvisor: clientes modelo map indisponível (%s)", e)
    return mapa


def _count_mes(mes: str, uid: str | None = None) -> int:
    supabase = _get_supabase()
    if not supabase:
        return 0
    try:
        q = supabase.table("receita_itens").select("id", count="exact").eq("data_ref", mes)
        if uid:
            q = q.eq("user_id", uid)
        res = q.execute()
        return res.count or 0
    except Exception as e:
        current_app.logger.info("finadvisor: count falhou (%s)", e)
        return 0

def _sum_mes(mes: str, uid: str | None = None) -> tuple[float, float]:
    """Soma do mês inteiro: (total_escritorio, total_assessor)."""
    supabase = _get_supabase()
    if not supabase:
        return 0.0, 0.0
    total_escr = 0.0
    total_ass  = 0.0
    page = 0
    page_size = 1000
    while True:
        start = page * page_size
        end = start + page_size - 1
        try:
            q = (
                supabase.table("receita_itens")
                .select("comissao_escritorio,valor_liquido")
                .eq("data_ref", mes)
                .range(start, end)
            )
            if uid:
                q = q.eq("user_id", uid)
            res = q.execute()
        except Exception as e:
            current_app.logger.info("finadvisor: _sum_mes falhou em page %s (%s)", page, e)
            break
        data = list(res.data or [])
        for r in data:
            total_escr += _to_float(r.get("comissao_escritorio"))
            total_ass  += _to_float(r.get("valor_liquido"))
        if len(data) < page_size:
            break
        page += 1
    return total_escr, total_ass

def _fetch_all_rows_mes(mes: str, uid: str | None = None) -> list[dict]:
    """
    Busca todas as linhas de receita_itens de um mês, paginando em lotes.
    Tenta com cliente_nome e faz fallback sem a coluna se necessário.
    """
    supabase = _get_supabase()
    if not supabase:
        return []

    cols_full = (
        "id,data_ref,cliente_codigo,cliente_nome,origem,familia,produto,detalhe,"
        "valor_bruto,imposto_pct,valor_liquido,comissao_bruta,comissao_liquida,comissao_escritorio,created_at"
    )
    cols_no_nome = (
        "id,data_ref,cliente_codigo,origem,familia,produto,detalhe,"
        "valor_bruto,imposto_pct,valor_liquido,comissao_bruta,comissao_liquida,comissao_escritorio,created_at"
    )

    out: list[dict] = []
    page = 0
    page_size = 1000
    used_fallback = False

    while True:
        start = page * page_size
        end = start + page_size - 1
        try:
            q = (
                supabase.table("receita_itens")
                .select(cols_full)
                .eq("data_ref", mes)
                .order("created_at", desc=True)
                .range(start, end)
            )
            if uid:
                q = q.eq("user_id", uid)
            res = q.execute()
            chunk = list(res.data or [])
        except Exception as e:
            msg = str(e)
            if "42703" in msg or "does not exist" in msg:
                # fallback: sem cliente_nome
                used_fallback = True
                q = (
                    supabase.table("receita_itens")
                    .select(cols_no_nome)
                    .eq("data_ref", mes)
                    .order("created_at", desc=True)
                    .range(start, end)
                )
                if uid:
                    q = q.eq("user_id", uid)
                res = q.execute()
                chunk = list(res.data or [])
            else:
                raise

        out.extend(chunk)
        if len(chunk) < page_size:
            break
        page += 1

    # se usamos fallback, enriquecer cliente_nome via public.clientes
    if used_fallback:
        nome_map = _clientes_nome_map_by_xp()
        for r in out:
            digits = _digits_only(r.get("cliente_codigo") or "")
            r["cliente_nome"] = nome_map.get(digits, "")

    return out

def _fetch_supabase_rows(mes: str, start: int, end: int, uid: str | None = None):
    """
    Busca um range de linhas de receita_itens para um mês.
    Tenta primeiro com cliente_nome; se der 42703, faz fallback sem a coluna e
    preenche o nome a partir de public.clientes.
    Retorna (rows, used_fallback: bool).
    """
    supabase = _get_supabase()
    if not supabase:
        return [], False

    cols_full = (
        "id,data_ref,cliente_codigo,cliente_nome,origem,familia,produto,detalhe,"
        "valor_bruto,imposto_pct,valor_liquido,comissao_bruta,comissao_liquida,comissao_escritorio,created_at"
    )
    cols_no_nome = (
        "id,data_ref,cliente_codigo,origem,familia,produto,detalhe,"
        "valor_bruto,imposto_pct,valor_liquido,comissao_bruta,comissao_liquida,comissao_escritorio,created_at"
    )

    # 1) tenta com cliente_nome
    try:
        q = (
            supabase.table("receita_itens")
            .select(cols_full)
            .eq("data_ref", mes)
            .order("created_at", desc=True)
            .range(start, end)
        )
        if uid:
            q = q.eq("user_id", uid)
        res = q.execute()
        return list(res.data or []), False
    except Exception as e:
        msg = str(e)
        if "42703" not in msg and "does not exist" not in msg:
            raise  # erro diferente -> propaga

    # 2) fallback sem cliente_nome
    q = (
        supabase.table("receita_itens")
        .select(cols_no_nome)
        .eq("data_ref", mes)
        .order("created_at", desc=True)
        .range(start, end)
    )
    if uid:
        q = q.eq("user_id", uid)
    res = q.execute()
    rows = list(res.data or [])

    # enriquecimento de nome via clientes (codigo_xp)
    mapa = _clientes_nome_map_by_xp()
    for r in rows:
        xp_digits = _digits_only(r.get("cliente_codigo") or "")
        r["cliente_nome"] = mapa.get(xp_digits, "")
    return rows, True


# ------------------- Views (Reconciliação de códigos) -------------------

@fin_bp.route("/corrigir-codigos", methods=["GET"])
@login_required
def corrigir_codigos_list():
    """
    Lista todas as linhas de receita_itens cujo cliente_codigo contenha o codigo_xp
    do assessor (vindo do metadata). Permite editar por linha.
    Exclui 'LANÇ. ADMINISTRATIVO...' e derivados.
    """
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return redirect(url_for("finadvisor.index"))

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for("finadvisor.index"))

    codigo_xp = _get_codigo_xp_from_meta()
    if not codigo_xp:
        flash("Não foi possível encontrar o 'codigo_xp' no seu perfil.", "error")
        return redirect(url_for("finadvisor.index"))

    # paginação simples
    page = max(int(request.args.get("page", 1)), 1)
    page_size = max(1, min(int(request.args.get("page_size", 200)), 1000))
    start = (page - 1) * page_size
    end = start + page_size - 1

    cols_full = (
        "id,data_ref,cliente_codigo,cliente_nome,origem,familia,produto,detalhe,"
        "valor_bruto,imposto_pct,valor_liquido,comissao_bruta,comissao_liquida,comissao_escritorio,created_at"
    )
    cols_no_nome = (
        "id,data_ref,cliente_codigo,origem,familia,produto,detalhe,"
        "valor_bruto,imposto_pct,valor_liquido,comissao_bruta,comissao_liquida,comissao_escritorio,created_at"
    )

    try:
        # 1) tenta com cliente_nome
        q = (
            supabase.table("receita_itens")
            .select(cols_full, count="exact")
            .ilike("cliente_codigo", f"%{codigo_xp}%")
            .eq("user_id", uid)
            .order("created_at", desc=True)
            .range(start, end)
        )
        res = q.execute()
        rows = list(res.data or [])
        # filtro: remove LANC. ADMINISTRATIVO e derivados
        rows = [
            r for r in rows
            if not str(r.get("familia") or "").upper().startswith("LANÇ. ADMINISTRATIVO")
        ]
        total = len(rows)
        used_fallback = False
    except Exception as e:
        msg = str(e)
        # 2) fallback: sem a coluna cliente_nome
        if "42703" in msg or "does not exist" in msg:
            try:
                q2 = (
                    supabase.table("receita_itens")
                    .select(cols_no_nome, count="exact")
                    .ilike("cliente_codigo", f"%{codigo_xp}%")
                    .eq("user_id", uid)
                    .order("created_at", desc=True)
                    .range(start, end)
                )
                res2 = q2.execute()
                rows = list(res2.data or [])
                # filtro: remove LANC. ADMINISTRATIVO e derivados
                rows = [
                    r for r in rows
                    if not str(r.get("familia") or "").upper().startswith("LANÇ. ADMINISTRATIVO")
                ]
                # enriquecer nome a partir de public.clientes (map por codigo_xp)
                nome_map = _clientes_nome_map_by_xp()
                for r in rows:
                    xp_digits = _digits_only(r.get("cliente_codigo") or "")
                    r["cliente_nome"] = nome_map.get(xp_digits, "")
                total = len(rows)
                used_fallback = True
            except Exception as e2:
                current_app.logger.exception("corrigir_codigos_list: fallback falhou: %s", e2)
                flash(f"Falha ao buscar itens para correção: {e2}", "error")
                return redirect(url_for("finadvisor.index"))
        else:
            current_app.logger.exception("corrigir_codigos_list: falha na consulta: %s", e)
            flash(f"Falha ao buscar itens para correção: {e}", "error")
            return redirect(url_for("finadvisor.index"))

    return render_template(
        "finadvisor_corrigir.html",
        codigo_xp=codigo_xp,
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        used_fallback=used_fallback,
    )

@fin_bp.route("/corrigir-codigos/<string:item_id>", methods=["POST"])
@login_required
def corrigir_codigos_update(item_id: str):
    """
    Atualiza o cliente_codigo de uma linha de receita_itens e sincroniza receita_clientes.
    """
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return redirect(url_for("finadvisor.corrigir_codigos_list"))

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for("finadvisor.corrigir_codigos_list"))

    novo_codigo = (request.form.get("novo_codigo") or "").strip()
    antigo_codigo = (request.form.get("antigo_codigo") or "").strip()
    cliente_nome = (request.form.get("cliente_nome") or "").strip() or None

    if not novo_codigo:
        flash("Informe o novo código do cliente.", "error")
        return redirect(url_for("finadvisor.corrigir_codigos_list"))

    # 1) Atualiza a linha em receita_itens (somente do dono)
    try:
        q = supabase.table("receita_itens").update({
            "cliente_codigo": novo_codigo
        }).eq("id", item_id).eq("user_id", uid)
        q.execute()
    except Exception as e:
        current_app.logger.exception("corrigir_codigos_update: update receita_itens falhou: %s", e)
        flash(f"Falha ao atualizar linha: {e}", "error")
        return redirect(url_for("finadvisor.corrigir_codigos_list"))

    # 2) Sincroniza a tabela receita_clientes (se existir)
    try:
        if antigo_codigo:
            supabase.table("receita_clientes").delete().eq("user_id", uid).eq("cliente_codigo", antigo_codigo).execute()

        payload = {"user_id": uid, "cliente_codigo": novo_codigo}
        if cliente_nome:
            payload["cliente_nome"] = cliente_nome

        supabase.table("receita_clientes").upsert(
            payload,
            on_conflict="user_id,cliente_codigo"
        ).execute()
    except Exception as e:
        current_app.logger.exception("corrigir_codigos_update: sync receita_clientes falhou: %s", e)
        flash(f"Atualizado em receita_itens", "warning")
        return redirect(url_for("finadvisor.corrigir_codigos_list"))

    flash("Código atualizado com sucesso.", "success")
    return redirect(url_for("finadvisor.corrigir_codigos_list"))


# -------------------------- View principal --------------------------

@fin_bp.route("/", methods=["GET"])
@login_required
def index():
    mes = (request.args.get("mes") or "").strip()
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 100))
    page = max(page, 1)
    page_size = max(1, min(page_size, 1000))

    if not mes:
        mes = _latest_month()

    uid = _uid()

    start = (page - 1) * page_size
    end = start + page_size - 1

    total = _count_mes(mes, uid=uid)

    rows = []
    used_fallback = False
    error_msg = ""
    try:
        rows, used_fallback = _fetch_supabase_rows(mes, start, end, uid=uid)
    except Exception as e:
        current_app.logger.exception("FinAdvisor: falha ao consultar Supabase: %s", e)
        error_msg = str(e)
        rows = []

    exibidos = len(rows)

    # Totais mensais (escritório + assessor)
    total_escritorio_mensal, total_assessor_mensal = _sum_mes(mes, uid=uid)
    soma_mensal = total_escritorio_mensal + total_assessor_mensal

    # ----------------- AGREGAÇÕES PARA O TEMPLATE (mês inteiro) -----------------
    try:
        todas_linhas = _fetch_all_rows_mes(mes, uid=uid)
    except Exception as e:
        current_app.logger.info("finadvisor: fallback agregações com página atual (%s)", e)
        todas_linhas = rows  # pior caso: usa apenas a página atual

    # Excluir 'LANÇ. ADMINISTRATIVO...' e derivados das AGREGACOES
    todas_linhas = [
        r for r in todas_linhas
        if not str(r.get("familia") or "").upper().startswith("LANÇ. ADMINISTRATIVO")
    ]

    nome_map = _clientes_nome_map_by_xp()
    modelo_map = _clientes_modelo_map_by_xp()

    # 1) clientes_list: soma valor_liquido por cliente (mês inteiro)
    agrup_cli: dict[str, dict] = {}
    for r in todas_linhas:
        cod_raw = (r.get("cliente_codigo") or "").strip()
        digits  = _digits_only(cod_raw)
        cod_key = digits or cod_raw or "-"
        val     = _to_float(r.get("valor_liquido"))

        if cod_key not in agrup_cli:
            nome = r.get("cliente_nome") or nome_map.get(digits, "")
            agrup_cli[cod_key] = {"codigo": cod_key, "nome": nome, "valor": 0.0}
        agrup_cli[cod_key]["valor"] += val

    clientes_list = sorted(agrup_cli.values(), key=lambda x: (x["nome"] or "").upper())

    # 2) series + modelos: uma linha do mês atual, colunas por modelo
    soma_por_modelo: dict[str, float] = {}
    for r in todas_linhas:
        digits = _digits_only(r.get("cliente_codigo") or "")
        md = (modelo_map.get(digits) or "TRADICIONAL").upper()
        soma_por_modelo[md] = soma_por_modelo.get(md, 0.0) + _to_float(r.get("valor_liquido"))

    modelos = sorted(soma_por_modelo.keys())
    serie_linha = {"mes": mes, "total": sum(soma_por_modelo.values())}
    for md in modelos:
        serie_linha[md] = soma_por_modelo[md]
    series = [serie_linha]

    # ----------------- RENDER -----------------
    return render_template(
        "finadvisor/index.html",
        mes=mes,
        mes_focus=mes,
        page=page,
        page_size=page_size,
        total=total,
        exibidos=exibidos,
        rows=rows,                     # tabela paginada
        used_fallback=used_fallback,
        error_msg=error_msg,
        total_escritorio_mensal=total_escritorio_mensal,
        total_assessor_mensal=total_assessor_mensal,
        soma_mensal=soma_mensal,
        modelos=modelos,               # agregados do mês inteiro
        series=series,
        clientes_list=clientes_list,
        source="supabase",
        view_version="v1",
    )
