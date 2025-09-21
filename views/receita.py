from flask import Blueprint, render_template, request, current_app, session
from utils import login_required
from collections import defaultdict
import json
import re
import unicodedata

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
        current_app.logger.debug("RECEITA: Cliente Supabase não disponível (usuário não autenticado)")
    return client


def _uid():
    # Usar a mesma lógica do security_middleware
    from security_middleware import get_current_user_id
    return get_current_user_id()

receita_bp = Blueprint("receita", __name__, url_prefix="/receita")
RECEITA_VIEW_VERSION = "v-supabase-xpmb-2025-09-08"


# ----------------- Helpers -----------------
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


def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_admin_family(familia: str) -> bool:
    n = _norm(familia or "")
    return n in {"lanc administrativo", "lanc adm"} or n.startswith("lanc adm")


def _user_key() -> str:
    u = session.get("user") or {}
    return (u.get("email") or u.get("nome") or "anon").strip().lower()


def _extract_digits(code: str) -> str:
    if not code:
        return ""
    ds = re.findall(r"\d+", str(code))
    if not ds:
        return ""
    ds.sort(key=len, reverse=True)
    return ds[0]


def _receita_por_modelo_mensal():
    """
    Busca receita escritório e assessor por modelo, mês a mês.
    CORRIGIDO: Usa agregação SQL direta para garantir valores corretos.

    Retorna: [
        {
            "mes": "2025-01",
            "modelos": {
                "TRADICIONAL": {"escritorio": 2000.0, "assessor": 1600.0},
                "ASSET": {"escritorio": 1500.0, "assessor": 1200.0},
                "FEE_BASED": {"escritorio": 3000.0, "assessor": 2400.0},
                "FEE_BASED_SEM_RV": {"escritorio": 1000.0, "assessor": 800.0}
            }
        },
        ...
    ]
    """
    supabase = _get_supabase()
    if not supabase:
        current_app.logger.warning("_receita_por_modelo_mensal: Supabase não disponível")
        return []

    uid = _uid()
    current_app.logger.error("🎯 RECEITA_MODELO_MENSAL: Processando para user_id = %s", uid)

    if not uid:
        current_app.logger.warning("_receita_por_modelo_mensal: Sem user_id")
        return []

    # Debug: log do user_id usado
    current_app.logger.info("RECEITA_MODELO_MENSAL: User ID da sessão: %s", uid)

    try:
        from collections import defaultdict
        from datetime import datetime

        # 1. Buscar mapeamento código -> modelo (igual ao anterior)
        clientes_result = supabase.table("clientes").select(
            "id, codigo_xp, codigo_mb, modelo"
        ).eq("user_id", uid).execute()

        clientes_data = clientes_result.data or []
        current_app.logger.info("RECEITA_MODELO_MENSAL: %d clientes encontrados", len(clientes_data))

        # Log da query de clientes para debug
        current_app.logger.info("RECEITA_MODELO_MENSAL: %d clientes encontrados para mapeamento", len(clientes_data))

        # Mapear código do cliente para modelo
        codigo_para_modelo = {}
        for cliente in clientes_data:
            modelo = cliente.get("modelo", "").strip() or "SEM_MODELO"

            codigo_xp = _extract_digits(cliente.get("codigo_xp") or "")
            codigo_mb = _extract_digits(cliente.get("codigo_mb") or "")

            if codigo_xp:
                codigo_para_modelo[codigo_xp] = modelo
            if codigo_mb:
                codigo_para_modelo[codigo_mb] = modelo

        # Log do mapeamento criado
        current_app.logger.info("RECEITA_MODELO_MENSAL: %d códigos mapeados para modelos", len(codigo_para_modelo))

        # 2. Usar RPC ou query direta para obter totais por mês (como o SQL que funcionou)
        year = datetime.now().year
        start_ym = f"{year}-01"
        next_year_start = f"{year + 1}-01"

        current_app.logger.info("RECEITA_MODELO_MENSAL: Buscando dados de %s até %s", start_ym, next_year_start)

        # Buscar TODOS os dados de uma vez, aplicando filtros como no SQL
        table_name = "receita_itens"
        try:
            supabase.table(table_name).select("cliente_codigo").limit(1).execute()
        except Exception:
            table_name = "receita_intens"
            current_app.logger.info("RECEITA_MODELO_MENSAL: Usando tabela fallback receita_intens")

        # Buscar dados usando paginação correta (sem limite artificial)
        try:
            receitas_data = []
            page_size = 1000
            offset = 0

            current_app.logger.info("RECEITA_MODELO_MENSAL: Iniciando busca paginada sem limite")

            while True:
                receitas_query = (
                    supabase.table(table_name)
                    .select("data_ref, cliente_codigo, comissao_escritorio, valor_liquido, familia")
                    .eq("user_id", uid)
                    .gte("data_ref", start_ym)
                    .lt("data_ref", next_year_start)
                    .not_.ilike("familia", "%administrativo%")  # Usar ilike como no SQL
                    .order("id")  # CORREÇÃO: Ordenar por ID em vez de data_ref
                    .range(offset, offset + page_size - 1)
                )

                page_result = receitas_query.execute()
                page_data = page_result.data or []

                if not page_data:
                    break

                receitas_data.extend(page_data)

                current_app.logger.info("RECEITA_MODELO_MENSAL: Página %d - %d registros (total: %d)",
                                       offset // page_size + 1, len(page_data), len(receitas_data))

                if len(page_data) < page_size:
                    break

                offset += page_size

                # Limite de segurança para evitar loops infinitos
                if offset > 100000:
                    current_app.logger.warning("RECEITA_MODELO_MENSAL: Limite de segurança atingido")
                    break

            current_app.logger.info("RECEITA_MODELO_MENSAL: %d registros obtidos com paginação", len(receitas_data))

            # Verificar registros de fevereiro especificamente para debug
            fev_registros = [r for r in receitas_data if r.get("data_ref", "").startswith("2025-02")]
            current_app.logger.info("RECEITA_MODELO_MENSAL: %d registros de fevereiro encontrados", len(fev_registros))

        except Exception as e:
            current_app.logger.error("RECEITA_MODELO_MENSAL: Erro na query paginada, usando fallback: %s", e)
            # Fallback para método anterior se query falhar
            return _receita_por_modelo_mensal_fallback(supabase, uid, codigo_para_modelo)

        # 3. Processar dados e agrupar por mês/modelo
        receitas_por_mes_modelo = defaultdict(lambda: defaultdict(lambda: {"escritorio": 0.0, "assessor": 0.0}))

        for r in receitas_data:
            data_ref = r.get("data_ref", "")
            if not data_ref:
                continue

            mes = data_ref[:7]  # YYYY-MM
            codigo = _extract_digits(r.get("cliente_codigo") or "")
            comissao_escritorio = _to_float(r.get("comissao_escritorio")) or 0.0
            valor_liquido = _to_float(r.get("valor_liquido")) or 0.0

            # Mapear para modelo (default TRADICIONAL se não encontrado)
            modelo = codigo_para_modelo.get(codigo, "TRADICIONAL")

            receitas_por_mes_modelo[mes][modelo]["escritorio"] += comissao_escritorio
            receitas_por_mes_modelo[mes][modelo]["assessor"] += valor_liquido

        # 4. Converter para formato da tabela
        resultado = []
        for mes in sorted(receitas_por_mes_modelo.keys()):
            modelos_dict = dict(receitas_por_mes_modelo[mes])

            # Log para debug de valores específicos
            if mes == "2025-02":
                total_escritorio = sum(m.get("escritorio", 0) for m in modelos_dict.values())
                current_app.logger.info("RECEITA_MODELO_MENSAL: Fevereiro - Total Escritório: %.2f", total_escritorio)
                for modelo, valores in modelos_dict.items():
                    current_app.logger.info("RECEITA_MODELO_MENSAL: Fevereiro - %s: Escrit=%.2f, Assess=%.2f",
                                           modelo, valores.get("escritorio", 0), valores.get("assessor", 0))

                # Verificar se o cálculo está correto
                esperado = 32881.30
                diferenca = abs(total_escritorio - esperado)
                if diferenca > 1.0:
                    current_app.logger.warning("RECEITA_MODELO_MENSAL: Fevereiro difere do esperado: %.2f vs %.2f (diff: %.2f)",
                                              total_escritorio, esperado, diferenca)
                else:
                    current_app.logger.info("RECEITA_MODELO_MENSAL: Fevereiro calculado corretamente: %.2f", total_escritorio)

            resultado.append({
                "mes": mes,
                "modelos": modelos_dict
            })

        current_app.logger.info("RECEITA_MODELO_MENSAL: %d meses processados", len(resultado))
        return resultado

    except Exception as e:
        current_app.logger.error("RECEITA_MODELO_MENSAL: Erro geral: %s", e)
        return []


def _receita_por_modelo_mensal_fallback(supabase, uid, codigo_para_modelo):
    """Fallback usando método de paginação anterior"""
    current_app.logger.info("RECEITA_MODELO_MENSAL: Usando método fallback com paginação")

    from collections import defaultdict
    from datetime import datetime

    year = datetime.now().year
    start_ym = f"{year}-01"
    next_year_start = f"{year + 1}-01"

    receitas_por_mes_modelo = defaultdict(lambda: defaultdict(lambda: {"escritorio": 0.0, "assessor": 0.0}))

    table_name = "receita_itens"
    try:
        supabase.table(table_name).select("cliente_codigo").limit(1).execute()
    except Exception:
        table_name = "receita_intens"

    LIMIT_PAGE = 1000
    offset = 0
    total_processado = 0

    while True:
        try:
            q = (
                supabase.table(table_name)
                .select("data_ref, cliente_codigo, comissao_escritorio, valor_liquido, familia")
                .gte("data_ref", start_ym)
                .lt("data_ref", next_year_start)
                .eq("user_id", uid)
                .order("data_ref")
            )
            res = q.range(offset, offset + LIMIT_PAGE - 1).execute()
        except Exception as e:
            current_app.logger.error("RECEITA_MODELO_MENSAL_FALLBACK: Erro na consulta: %s", e)
            break

        rows = list(res.data or [])
        if not rows:
            break

        for r in rows:
            total_processado += 1
            data_ref = r.get("data_ref", "")
            if not data_ref:
                continue

            # Filtrar registros administrativos (usando mesma lógica do SQL)
            familia = r.get("familia", "") or ""
            if familia and "administrativo" in familia.lower():
                continue

            mes = data_ref[:7]  # YYYY-MM
            codigo = _extract_digits(r.get("cliente_codigo") or "")
            comissao_escritorio = _to_float(r.get("comissao_escritorio")) or 0.0
            valor_liquido = _to_float(r.get("valor_liquido")) or 0.0

            modelo = codigo_para_modelo.get(codigo, "TRADICIONAL")
            receitas_por_mes_modelo[mes][modelo]["escritorio"] += comissao_escritorio
            receitas_por_mes_modelo[mes][modelo]["assessor"] += valor_liquido

        offset += len(rows)

        if offset > 50000:
            current_app.logger.warning("RECEITA_MODELO_MENSAL_FALLBACK: Limite de paginação atingido")
            break

    # Converter para formato da tabela
    resultado = []
    for mes in sorted(receitas_por_mes_modelo.keys()):
        resultado.append({
            "mes": mes,
            "modelos": dict(receitas_por_mes_modelo[mes])
        })

    return resultado


# ----------------- Preferências (produtos selecionados) -----------------
def _load_product_prefs() -> list[str]:
    key = _user_key()
    supabase = _get_supabase()
    if supabase:
        try:
            q = supabase.table("user_prefs").select("value").eq("user_key", key).eq("key", "recorrencia_produtos")
            uid = _uid()
            if uid:
                q = q.eq("user_id", uid)
            res = q.limit(1).execute()
            data = (res.data or [])
            if data:
                val = data[0].get("value")
                if isinstance(val, str):
                    return json.loads(val)
                if isinstance(val, list):
                    return val
        except Exception:
            pass
    try:
        val = session.get("recorrencia_produtos")
        if val:
            if isinstance(val, str):
                return json.loads(val)
            if isinstance(val, list):
                return val
    except Exception:
        pass
    return []


def _save_product_prefs(selected: list[str]):
    key = _user_key()
    payload = json.dumps(selected, ensure_ascii=False)
    supabase = _get_supabase()
    if supabase:
        try:
            supabase.table("user_prefs").upsert(
                {"user_key": key, "key": "recorrencia_produtos", "value": payload, "user_id": _uid()},
                on_conflict="user_key,key",
            ).execute()
            session["recorrencia_produtos"] = payload
            return
        except Exception as e:
            current_app.logger.info("Falha ao salvar prefs (Supabase). Usando sessão. %s", e)
    session["recorrencia_produtos"] = payload


# ----------------- Supabase (fetch paginado) -----------------
def _fetch_supabase_rows_paged(page_size: int = 1000, max_pages: int = 200):
    """Busca receita_itens paginando e faz fallback se faltar alguma coluna."""
    supabase = _get_supabase()
    if not supabase:
        current_app.logger.error("RECEITA: Cliente Supabase não disponível - usuário não autenticado")
        return []  # Retorna lista vazia em vez de erro

    def fetch_with_cols(cols: str):
        rows = []
        page = 0
        while True:
            start = page * page_size
            end = start + page_size - 1
            q = supabase.table("receita_itens").select(cols).order("id", desc=False).range(start, end)  # FIX: Ordenação por ID
            uidv = _uid()
            if uidv:
                q = q.eq("user_id", uidv)
            res = q.execute()
            chunk = list(res.data or [])
            rows.extend(chunk)
            if len(chunk) < page_size:
                break
            page += 1
            if page >= max_pages:
                current_app.logger.warning(
                    "Receita: atingiu max_pages=%s (trouxe %s linhas)",
                    max_pages, len(rows)
                )
                break
        return rows

    cols_full = "data_ref, cliente_codigo, cliente_nome, produto, familia, valor_liquido, comissao_escritorio"
    try:
        return fetch_with_cols(cols_full)
    except Exception as e1:
        msg1 = str(e1)
        if "42703" in msg1 or "does not exist" in msg1:
            cols_no_name = "data_ref, cliente_codigo, produto, familia, valor_liquido, comissao_escritorio"
            try:
                return fetch_with_cols(cols_no_name)
            except Exception as e2:
                msg2 = str(e2)
                if "42703" in msg2 or "does not exist" in msg2:
                    cols_no_prod = "data_ref, cliente_codigo, familia, valor_liquido, comissao_escritorio"
                    try:
                        return fetch_with_cols(cols_no_prod)
                    except Exception as e3:
                        msg3 = str(e3)
                        if "42703" in msg3 or "does not exist" in msg3:
                            cols_min = "data_ref, cliente_codigo, valor_liquido, comissao_escritorio"
                            return fetch_with_cols(cols_min)
                        raise
                raise
        raise


# ----------------- Mapas XP/MB -----------------
def _fetch_clientes_maps():
    """
    Retorna:
      - code_to_name : dígitos(XP|MB) -> nome
      - code_to_canon: dígitos(XP|MB) -> canon (prioriza XP)
      - code_to_kind : dígitos(XP) -> 'XP', dígitos(MB) -> 'MB'
      - canon_parts  : canon -> {'xp': <codigo_xp ou ''>, 'mb': <codigo_mb ou ''>}
    """
    code_to_name:  dict[str, str] = {}
    code_to_canon: dict[str, str] = {}
    code_to_kind:  dict[str, str] = {}
    canon_parts:   dict[str, dict[str, str]] = {}

    supabase = _get_supabase()
    if not supabase:
        return code_to_name, code_to_canon, code_to_kind, canon_parts

    try:
        q = supabase.table("clientes").select("codigo_xp,codigo_mb,nome").range(0, 200000)
        uidc = _uid()
        if uidc:
            q = q.eq("user_id", uidc)
        res = q.execute()
        for r in (res.data or []):
            nome = (r.get("nome") or "").strip()
            xp   = _extract_digits((r.get("codigo_xp") or "").strip())
            mb   = _extract_digits((r.get("codigo_mb") or "").strip())

            canon = xp or mb
            if not canon:
                continue

            parts = canon_parts.setdefault(canon, {"xp": "", "mb": ""})
            if xp: parts["xp"] = xp
            if mb: parts["mb"] = mb

            if xp:
                code_to_name[xp]  = nome or xp
                code_to_canon[xp] = canon
                code_to_kind[xp]  = "XP"
            if mb:
                code_to_name[mb]  = nome or mb
                code_to_canon[mb] = canon
                code_to_kind[mb]  = "MB"
    except Exception as e:
        current_app.logger.info("Clientes maps XP/MB indisponível: %s", e)

    return code_to_name, code_to_canon, code_to_kind, canon_parts


# ----------------- Core de agregação -----------------
def _agrupar_estruturas(
    rows,
    code_to_name: dict[str, str],
    code_to_canon: dict[str, str],
    code_to_kind: dict[str, str],
    selected_products: list[str] | None = None,
    produto_presente: bool = True,
    familia_presente: bool = True,
):
    """
    Agrega mensalmente e por cliente (CANÔNICO), diferenciando XP/MB:
      - by_month_clientes_assessor[m][canon]    -> total assessor
      - by_month_clientes_escritorio[m][canon]  -> total escritório
      - by_kind_assessor[m][canon]['XP'|'MB']   -> fatias assessor
      - by_kind_escritorio[m][canon]['XP'|'MB'] -> fatias escritório
    """
    all_months = sorted({(r.get("data_ref") or "").strip() for r in rows if (r.get("data_ref") or "").strip()})

    by_month_escritorio = defaultdict(float)
    by_month_assessor   = defaultdict(float)
    rec_assessor_by_month = defaultdict(float)

    by_month_clientes_assessor   = defaultdict(lambda: defaultdict(float))   # [mes][canon]
    by_month_clientes_escritorio = defaultdict(lambda: defaultdict(float))   # [mes][canon]

    by_kind_assessor   = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))   # [mes][canon][kind]
    by_kind_escritorio = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    products_set = set()
    fallback_names_by_code: dict[str, str] = {}
    selected_set = set(selected_products or [])

    for r in rows:
        mes = (r.get("data_ref") or "").strip()
        if not mes:
            continue

        val_liq = _to_float(r.get("valor_liquido"))
        val_esc = _to_float(r.get("comissao_escritorio"))

        produto = (r.get("produto") or "").strip() if r.get("produto") is not None else ""
        familia = (r.get("familia") or "").strip() if r.get("familia") is not None else ""
        if produto_presente and produto:
            products_set.add(produto)

        # Totais mensais (sempre contam)
        by_month_escritorio[mes] += val_esc
        ignore_for_assessor = (familia_presente and _is_admin_family(familia))
        if not ignore_for_assessor:
            by_month_assessor[mes] += val_liq
            if not produto_presente:
                rec_assessor_by_month[mes] += val_liq
            else:
                if not selected_set or (produto in selected_set):
                    rec_assessor_by_month[mes] += val_liq

        # Por cliente (XP/MB -> CANÔNICO + KIND)
        cod_raw = (r.get("cliente_codigo") or "").strip()
        code_original = _extract_digits(cod_raw)
        if not code_original:
            continue

        # fallback de nome vindo da própria linha
        nome_item = (r.get("cliente_nome") or "").strip() if r.get("cliente_nome") is not None else ""
        if nome_item and code_original not in fallback_names_by_code:
            fallback_names_by_code[code_original] = nome_item

        canon = code_to_canon.get(code_original, code_original)
        kind  = code_to_kind.get(code_original, "XP" if code_original == canon else "MB")

        if not ignore_for_assessor:
            by_month_clientes_assessor[mes][canon] += val_liq
            by_kind_assessor[mes][canon][kind]    += val_liq

        by_month_clientes_escritorio[mes][canon] += val_esc
        by_kind_escritorio[mes][canon][kind]     += val_esc

    # Saídas mensais totais
    hist_mensal = [
        {"mes": m, "escritorio": by_month_escritorio.get(m, 0.0), "assessor": by_month_assessor.get(m, 0.0)}
        for m in all_months
    ]
    hist_recorrente = [{"mes": m, "assessor": rec_assessor_by_month.get(m, 0.0)} for m in all_months]
    produtos_ordenados = sorted([p for p in products_set if p])

    # nome por CANÔNICO
    def name_for(canon: str) -> str:
        if canon in code_to_name and code_to_name[canon]:
            return code_to_name[canon]
        return fallback_names_by_code.get(canon) or code_to_name.get(canon) or canon

    # opções (códigos CANÔNICOS observados)
    canons_set = set()
    for m in all_months:
        canons_set |= set(by_month_clientes_assessor[m].keys())
        canons_set |= set(by_month_clientes_escritorio[m].keys())

    clientes_opts = sorted(
        [{"codigo": c, "nome": name_for(c)} for c in canons_set],
        key=lambda x: (x["nome"] or x["codigo"])
    )

    return (
        hist_mensal,
        hist_recorrente,
        by_month_clientes_assessor,
        by_month_clientes_escritorio,
        produtos_ordenados,
        clientes_opts,
        fallback_names_by_code,
        by_kind_assessor,
        by_kind_escritorio,
    )


# ----------------- Views -----------------
@receita_bp.route("/", methods=["GET"])
@login_required
def index():
    mes_filter = (request.args.get("mes") or "").strip()
    cliente_filter_raw = (request.args.get("cliente") or "").strip()  # pode vir XP ou MB

    source = "supabase-paged"
    error_msg = ""
    try:
        rows = _fetch_supabase_rows_paged(page_size=1000)
    except Exception as e:
        current_app.logger.warning("RECEITA: Falha ao consultar Supabase (usuário não autenticado): %s", e)
        source = "supabase-error"
        error_msg = "Usuário não autenticado"
        rows = []

    produto_presente = any("produto" in r for r in rows) or (rows and rows[0].get("produto") is not None)
    familia_presente = any("familia" in r for r in rows) or (rows and rows[0].get("familia") is not None)

    # mapas (XP/MB)
    code_to_name, code_to_canon, code_to_kind, canon_parts = _fetch_clientes_maps()

    # 1ª passagem (listas base)
    (
        hist_mensal,
        hist_recorrente,
        by_month_clientes_assessor,
        by_month_clientes_escritorio,
        produtos_all,
        clientes_opts,
        fallback_names_by_code,
        by_kind_assessor,
        by_kind_escritorio,
    ) = _agrupar_estruturas(
        rows, code_to_name, code_to_canon, code_to_kind,
        selected_products=None,
        produto_presente=produto_presente, familia_presente=familia_presente
    )

    saved_products = _load_product_prefs()
    selected_products = saved_products[:] if saved_products else produtos_all[:]

    # 2ª passagem (recorrente com preferências)
    (
        hist_mensal,
        hist_recorrente,
        by_month_clientes_assessor,
        by_month_clientes_escritorio,
        _,
        _,
        _,
        by_kind_assessor,
        by_kind_escritorio,
    ) = _agrupar_estruturas(
        rows, code_to_name, code_to_canon, code_to_kind,
        selected_products=selected_products,
        produto_presente=produto_presente, familia_presente=familia_presente
    )

    # ---- Tabela "Receita por cliente" (com XP/MB) ----
    clientes_por_mes = []
    all_months = [h["mes"] for h in hist_mensal]

    # filtro por cliente: aceita XP ou MB e converte para CANÔNICO
    filter_digits = _extract_digits(cliente_filter_raw)
    filter_code = code_to_canon.get(filter_digits, filter_digits)

    for m in all_months:
        if mes_filter and m != mes_filter:
            continue

        total_mes_escritorio = sum(by_month_clientes_escritorio[m].values()) or 0.0
        codes = set(by_month_clientes_escritorio[m].keys()) | set(by_month_clientes_assessor[m].keys())

        itens = []
        for code in codes:  # code já é canônico
            if filter_code and code != filter_code:
                continue

            nome = code_to_name.get(code) or fallback_names_by_code.get(code) or code
            valor_assessor   = by_month_clientes_assessor[m].get(code, 0.0)
            valor_escritorio = by_month_clientes_escritorio[m].get(code, 0.0)

            kind_ass = by_kind_assessor[m][code]
            kind_esc = by_kind_escritorio[m][code]
            ass_xp = kind_ass.get("XP", 0.0)
            ass_mb = kind_ass.get("MB", 0.0)
            esc_xp = kind_esc.get("XP", 0.0)
            esc_mb = kind_esc.get("MB", 0.0)

            itens.append({
                "codigo": code,
                "codigo_exib": code,
                "nome": nome,
                "valor_assessor": valor_assessor,
                "valor_escritorio": valor_escritorio,
                "assessor_xp": ass_xp,
                "assessor_mb": ass_mb,
                "escritorio_xp": esc_xp,
                "escritorio_mb": esc_mb,
                "pct": (valor_escritorio / total_mes_escritorio) if total_mes_escritorio > 0 else 0.0,
            })
        itens.sort(key=lambda x: x["valor_escritorio"], reverse=True)
        clientes_por_mes.append({"mes": m, "itens": itens, "total_mes_escritorio": total_mes_escritorio})

    # Buscar receita por modelo mês a mês
    receita_por_modelo = _receita_por_modelo_mensal()

    return render_template(
        "receita/index.html",
        mes_filter=mes_filter,
        cliente_filter=cliente_filter_raw,
        cliente_filter_canon=filter_code,  # usado no <select>
        hist_mensal=hist_mensal,
        hist_recorrente=hist_recorrente,
        clientes_por_mes=clientes_por_mes,
        produtos=produtos_all,
        clientes=clientes_opts,
        selected_products=selected_products,
        produto_presente=produto_presente,
        source=source,
        view_version=RECEITA_VIEW_VERSION,
        error_msg=error_msg,
        receita_por_modelo=receita_por_modelo,
    )


# ✅ Endpoint explicitado para bater com o template (url_for('receita.recorrente_partial'))
@receita_bp.route("/recorrente-partial", methods=["GET"], endpoint="recorrente_partial")
@login_required
def recorrente_partial():
    """Recalcula a recorrente e SALVA as preferências de produtos."""
    try:
        rows = _fetch_supabase_rows_paged(page_size=1000)
    except Exception as e:
        current_app.logger.exception("Receita: falha ao consultar Supabase (partial): %s", e)
        return render_template("receita/_recorrente.html",
                               hist_recorrente=[],
                               produto_presente=False)

    produto_presente = any("produto" in r for r in rows) or (rows and rows[0].get("produto") is not None)
    familia_presente = any("familia" in r for r in rows) or (rows and rows[0].get("familia") is not None)

    selected_products = request.args.getlist("produtos")
    _save_product_prefs(selected_products)

    code_to_name, code_to_canon, code_to_kind, _ = _fetch_clientes_maps()
    hist_mensal, hist_recorrente, _, _, _, _, _, _, _ = _agrupar_estruturas(
        rows,
        code_to_name,
        code_to_canon,
        code_to_kind,
        selected_products=selected_products,
        produto_presente=produto_presente,
        familia_presente=familia_presente
    )

    return render_template("receita/_recorrente.html",
                           hist_recorrente=hist_recorrente,
                           produto_presente=produto_presente)
