from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from utils import login_required
import os
import re
import io
import csv
from typing import List, Dict
from cache_manager import cached_by_user, invalidate_user_cache
from datetime import datetime

# Se o NET total estiver salvo em centavos no banco, defina NET_TOTAL_IN_CENTS=1 no .env
NET_TOTAL_IN_CENTS = os.getenv("NET_TOTAL_IN_CENTS", "0").lower() in ("1", "true", "yes")

# 🔒 Import protegido: não quebra se Supabase não estiver configurado
try:
    from supabase_client import get_supabase_client
except Exception as e:
    get_supabase_client = None
    import logging
    logging.getLogger(__name__).warning("Supabase indisponível na carga do módulo: %s", e)

def _get_supabase():
    """
    SEGURANÇA: Obtém cliente Supabase autenticado APENAS para o usuário atual.
    Retorna None se não há usuário válido para evitar vazamento de dados.
    """
    if not get_supabase_client:
        return None
    client = get_supabase_client()
    if client is None:
        current_app.logger.debug("CLIENTES: Cliente Supabase não disponível (usuário não autenticado)")
    return client

clientes_bp = Blueprint('clientes', __name__, url_prefix='/clientes')

# ----------------- Helpers -----------------
# ✅ inclui ASSET como modelo permitido
ALLOWED_MODELOS = {"TRADICIONAL", "ASSET", "FEE_BASED", "FEE_BASED_SEM_RV"}

# Headers esperados no template
_TEMPLATE_HEADERS = [
    "nome", "modelo", "repasse",
    "codigo_xp", "codigo_mb",
    "net_xp", "net_xp_global", "net_mb"
]

def _norm_modelo(v: str) -> str:
    """
    Normaliza o texto do modelo para os valores aceitos e
    retorna 'TRADICIONAL' quando vier algo inválido.
    """
    if not v:
        return "TRADICIONAL"
    s = str(v).strip().upper().replace(" ", "_")
    return s if s in ALLOWED_MODELOS else "TRADICIONAL"

def _to_float(x):
    """Converte qualquer coisa para float de forma segura (aceita '1.234,56')."""
    if x is None:
        return 0.0
    s = str(x).strip()
    if s == "" or s.upper() == "NULL":
        return 0.0
    # Remove separador de milhar e normaliza decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        # remove prefixos como R$, % etc.
        m = re.search(r"-?\d+(\.\d+)?", s)
        if m:
            s = m.group(0)
        return float(s)
    except Exception:
        current_app.logger.warning("Valor float inválido: %r", x)
        return 0.0

def _to_int_repasse(x, default=35):
    """
    Converte para int de forma segura; se vier sujo (UUID etc.), cai no default.
    Só permite 35 ou 50.
    """
    if x is None:
        return default
    s = str(x).strip()
    m = re.search(r'-?\d+', s)
    if not m:
        return default
    try:
        v = int(m.group(0))
        return 50 if v == 50 else 35
    except Exception:
        return default

# ----- Filtro Jinja para moeda BRL -----
def _brl(value):
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "R$ 0,00"
    s = f"{n:,.2f}"                  # 1234567.89 -> '1,234,567.89'
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")  # -> '1.234.567,89'
    return f"R$ {s}"

clientes_bp.add_app_template_filter(_brl, name="brl")

def _uid():
    # Usar a mesma lógica do security_middleware
    from security_middleware import get_current_user_id
    return get_current_user_id()

# ----------------- Views -----------------
@clientes_bp.route('/')
@login_required
def index():
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return render_template('clientes/index.html',
                             clientes=[],
                             filtros={"q": "", "modelo": "", "letra": ""},
                             stats_by_model={},
                             modelos_ordenados=[],
                             letras_ordenadas=[],
                             total_clientes=0)

    # ── filtros vindos da URL ───────────────────────────────────────────────
    q_txt = (request.args.get('q') or '').strip()              # código XP/MB
    modelo_raw = (request.args.get('modelo') or '').strip()    # modelo
    letra_filter = (request.args.get('letra') or '').strip()   # primeira letra do nome
    modelo_filter = _norm_modelo(modelo_raw) if modelo_raw else ""

    uid = _uid()

    try:
        # monta a query base
        query = supabase.table("clientes").select(
            "id, nome, modelo, repasse, net_total, net_xp, net_xp_global, net_mb, codigo_xp, codigo_mb"
        )
        if uid:
            query = query.eq("user_id", uid)

        # aplica filtro por modelo, se houver
        if modelo_filter:
            query = query.eq("modelo", modelo_filter)

        rows = []
        if q_txt:
            pattern = f"%{q_txt}%"
            # tenta o filtro no banco (OR em codigo_xp OU codigo_mb)
            try:
                query2 = query.or_(f"codigo_xp.ilike.{pattern},codigo_mb.ilike.{pattern}")
                res = query2.execute()
                rows = res.data or []
            except Exception:
                # fallback: busca sem filtro e filtra em memória
                res = query.execute()
                base = res.data or []
                ql = q_txt.lower()
                rows = [
                    r for r in base
                    if ql in str(r.get("codigo_xp") or "").lower()
                    or ql in str(r.get("codigo_mb") or "").lower()
                ]
        else:
            # sem filtro de código
            res = query.execute()
            rows = res.data or []

        # aplica filtro por primeira letra do nome, se houver
        if letra_filter and letra_filter.upper() in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            letra_upper = letra_filter.upper()
            rows = [
                r for r in rows
                if (r.get("nome") or "").strip().upper().startswith(letra_upper)
            ]

        # mapeia/normaliza para o template
        clientes = []
        for r in rows:
            clientes.append({
                "id": r.get("id"),  # UUID do Supabase
                "nome": r.get("nome") or "",
                "modelo": _norm_modelo(r.get("modelo")),
                "repasse": _to_int_repasse(r.get("repasse"), 35),
                # divide por 100 se vier em centavos
                "net_total": (_to_float(r.get("net_total")) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(r.get("net_total")),
                "codigo_xp": (r.get("codigo_xp") or "").strip(),
                "codigo_mb": (r.get("codigo_mb") or "").strip(),
            })

        clientes.sort(key=lambda x: (x["nome"] or "").upper())

        # Calcular estatísticas por modelo
        stats_by_model = {}
        total_clientes = len(clientes)

        for cliente in clientes:
            modelo = cliente.get("modelo", "N/A")
            if modelo not in stats_by_model:
                stats_by_model[modelo] = 0
            stats_by_model[modelo] += 1

        # Ordenar modelos para exibição consistente
        modelos_ordenados = sorted(stats_by_model.keys())

        # Gerar lista de letras disponíveis (buscar todas as primeiras letras dos clientes)
        try:
            all_res = supabase.table("clientes").select("nome").eq("user_id", uid).execute() if uid else None
            all_clientes = all_res.data or [] if all_res else []
            letras_disponiveis = set()
            for c in all_clientes:
                nome = (c.get("nome") or "").strip()
                if nome:
                    primeira_letra = nome[0].upper()
                    if primeira_letra.isalpha():
                        letras_disponiveis.add(primeira_letra)
            letras_ordenadas = sorted(list(letras_disponiveis))
        except Exception:
            letras_ordenadas = []

        return render_template('clientes/index.html',
                             clientes=clientes,
                             filtros={"q": q_txt, "modelo": modelo_filter, "letra": letra_filter},
                             stats_by_model=stats_by_model,
                             modelos_ordenados=modelos_ordenados,
                             letras_ordenadas=letras_ordenadas,
                             total_clientes=total_clientes)

    except Exception:
        current_app.logger.exception("Falha ao listar clientes do Supabase")
        flash("Falha ao listar clientes do Supabase.", "warning")
        return render_template('clientes/index.html',
                             clientes=[],
                             filtros={"q": q_txt, "modelo": modelo_filter, "letra": letra_filter},
                             stats_by_model={},
                             modelos_ordenados=[],
                             letras_ordenadas=[],
                             total_clientes=0)

@clientes_bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        nome = request.form.get('nome') or ''
        modelo = _norm_modelo(request.form.get('modelo') or 'TRADICIONAL')
        repasse = _to_int_repasse(request.form.get('repasse'), 35)

        cxp = (request.form.get('codigo_xp') or '').strip()
        cmb = (request.form.get('codigo_mb') or '').strip()

        net_xp        = _to_float(request.form.get('net_xp'))
        net_xp_global = _to_float(request.form.get('net_xp_global'))
        net_mb        = _to_float(request.form.get('net_mb'))
        net_total     = net_xp + net_xp_global + net_mb

        supabase = _get_supabase()
        if not supabase:
            flash("Supabase indisponível.", "warning")
            return redirect(url_for('clientes.index'))

        try:
            uid = _uid()
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for('clientes.novo'))

            payload = {
                "nome": nome,
                "modelo": modelo,
                "repasse": repasse,
                "codigo_xp": cxp or None,
                "codigo_mb": cmb or None,
                "net_xp": net_xp,
                "net_xp_global": net_xp_global,
                "net_mb": net_mb,
                "net_total": net_total,
                "user_id": uid,  # 👈 garante o dono
            }

            res = supabase.table("clientes").insert(payload).execute()
            current_app.logger.info("Supabase insert clientes -> %s", getattr(res, "data", None))

            # Invalidar cache de clientes
            invalidate_user_cache('clientes_list')

            flash('Cliente cadastrado.', 'success')
        except Exception:
            current_app.logger.exception("Falha ao inserir no Supabase")
            flash('Falha ao inserir no Supabase.', 'warning')

        return redirect(url_for('clientes.index'))

    return render_template('clientes/novo.html')

@clientes_bp.route('/<string:id>/editar', methods=['GET', 'POST'])
@login_required
def editar(id: str):
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return redirect(url_for('clientes.index'))

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for('clientes.index'))

    if request.method == 'POST':
        nome   = request.form.get('nome') or ''
        modelo = _norm_modelo(request.form.get('modelo') or 'TRADICIONAL')
        repasse = _to_int_repasse(request.form.get('repasse'), 35)

        cxp = (request.form.get('codigo_xp') or '').strip()
        cmb = (request.form.get('codigo_mb') or '').strip()

        net_xp        = _to_float(request.form.get('net_xp'))
        net_xp_global = _to_float(request.form.get('net_xp_global'))
        net_mb        = _to_float(request.form.get('net_mb'))
        net_total     = net_xp + net_xp_global + net_mb

        try:
            payload = {
                "nome": nome,
                "modelo": modelo,
                "repasse": repasse,
                "codigo_xp": cxp or None,
                "codigo_mb": cmb or None,
                "net_xp": net_xp,
                "net_xp_global": net_xp_global,
                "net_mb": net_mb,
                "net_total": net_total,
            }
            # filtra por id e user_id (defensivo se service role)
            supabase.table("clientes").update(payload).eq("id", id).eq("user_id", uid).execute()

            # Invalidar caches relacionados
            invalidate_user_cache('clientes_list')
            invalidate_user_cache('dashboard_data')

            flash('Cliente atualizado com sucesso.', 'success')
        except Exception:
            current_app.logger.exception("Falha ao atualizar no Supabase")
            flash('Falha ao atualizar no Supabase.', 'warning')

        return redirect(url_for('clientes.index'))

    # GET -> carrega o registro para preencher o formulário (filtrando por dono)
    try:
        res = (
            supabase.table("clientes")
            .select("id, nome, modelo, repasse, codigo_xp, codigo_mb, net_xp, net_xp_global, net_mb, net_total")
            .eq("id", id)
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )

        rows = res.data or []
        if not rows:
            flash('Cliente não encontrado no Supabase.', 'warning')
            return redirect(url_for('clientes.index'))

        r = rows[0]
        c = {
            "id": r.get("id"),
            "nome": r.get("nome") or "",
            "modelo": _norm_modelo(r.get("modelo")),
            "repasse": _to_int_repasse(r.get("repasse"), 35),
            "codigo_xp": (r.get("codigo_xp") or ""),
            "codigo_mb": (r.get("codigo_mb") or ""),
            "net_xp": _to_float(r.get("net_xp")),
            "net_xp_global": _to_float(r.get("net_xp_global")),
            "net_mb": _to_float(r.get("net_mb")),
            "_raw_net_total": r.get("net_total"),
            "net_total": (_to_float(r.get("net_total")) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(r.get("net_total")),
        }

        return render_template('clientes/editar.html', c=c)

    except Exception:
        current_app.logger.exception("Falha ao carregar cliente do Supabase")
        flash('Falha ao carregar cliente do Supabase.', 'warning')
        return redirect(url_for('clientes.index'))

@clientes_bp.route('/<string:id>/excluir', methods=['POST'])
@login_required
def excluir(id: str):
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return redirect(url_for('clientes.index'))

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for('clientes.index'))

    try:
        # apaga apenas o registro do dono
        supabase.table("clientes").delete().eq("id", id).eq("user_id", uid).execute()

        # Invalidar caches relacionados
        invalidate_user_cache('clientes_list')
        invalidate_user_cache('dashboard_data')

        flash('Cliente excluído com sucesso.', 'success')
    except Exception:
        current_app.logger.exception("Falha ao excluir no Supabase")
        flash('Falha ao excluir no Supabase.', 'warning')

    return redirect(url_for('clientes.index'))

# ----------------- Importação em massa -----------------
def _make_template_csv() -> str:
    """Gera um CSV em memória com cabeçalho e 1 linha exemplo."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_TEMPLATE_HEADERS)
    # exemplo (pode editar/duplicar à vontade)
    w.writerow(["Fulano da Silva", "TRADICIONAL", "35", "1234567", "", "1000,00", "0", "500,50"])
    return buf.getvalue()

def _make_template_xlsx() -> bytes:
    """Gera um XLSX em memória com cabeçalho e 1 linha exemplo."""
    try:
        from openpyxl import Workbook
    except Exception:
        raise RuntimeError("Dependência 'openpyxl' não encontrada. Instale-a para baixar o template .xlsx.")
    wb = Workbook()
    ws = wb.active
    ws.title = "ImportarClientes"
    ws.append(_TEMPLATE_HEADERS)
    ws.append(["Fulano da Silva", "TRADICIONAL", "35", "1234567", "", "1000,00", "0", "500,50"])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()

def _norm_header(h: str) -> str:
    if not h:
        return ""
    s = h.strip().lower().replace(" ", "_")
    # remoção simples de acentos/c-cedilha
    s = (s.replace("ç","c").replace("ã","a").replace("â","a").replace("á","a")
           .replace("é","e").replace("ê","e").replace("í","i")
           .replace("ó","o").replace("ô","o").replace("ú","u"))
    return s

# mapeamento de sinônimos -> nome interno
_HEADER_MAP = {
    "nome": "nome",
    "modelo": "modelo",
    "repasse": "repasse",
    "codigo_xp": "codigo_xp",
    "codigo_xp.": "codigo_xp",
    "codigo xp": "codigo_xp",
    "código_xp": "codigo_xp",
    "código xp": "codigo_xp",
    "codigo_mb": "codigo_mb",
    "codigo mb": "codigo_mb",
    "código_mb": "codigo_mb",
    "código mb": "codigo_mb",
    "net_xp": "net_xp",
    "net_xp_global": "net_xp_global",
    "net_mb": "net_mb",
    "net total": "net_total",  # ignoramos; derivamos dos outros
}

def _parse_import_file(file_storage) -> List[Dict]:
    """
    Lê .csv ou .xlsx e retorna linhas limpas para 'clientes'.
    - CSV: detecta delimitador (',' ou ';'), mapeia cabeçalhos equivalentes.
    - XLSX: lê a primeira planilha, usa a primeira linha como cabeçalho.
    Converte números com ,/.; normaliza 'modelo' e 'repasse'.
    """
    filename = (getattr(file_storage, "filename", "") or "").lower()

    # --- CSV ---
    if filename.endswith(".csv"):
        content = file_storage.read()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        # detectar delimitador automaticamente
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ","

        # ler cabeçalho bruto
        buf = io.StringIO(text)
        raw_reader = csv.reader(buf, delimiter=delimiter)
        try:
            raw_headers = next(raw_reader)
        except StopIteration:
            raise ValueError("CSV vazio.")

        headers_norm = [_norm_header(h) for h in raw_headers]
        headers_final = [_HEADER_MAP.get(h, h) for h in headers_norm]

        required = {"nome","modelo","repasse","codigo_xp","codigo_mb","net_xp","net_xp_global","net_mb"}
        present = set(headers_final)
        missing = [h for h in required if h not in present]
        if missing:
            raise ValueError("Template inválido. Faltam colunas: " + ", ".join(sorted(missing)))

        # constrói DictReader com cabeçalhos finais
        buf2 = io.StringIO(text)
        reader = csv.DictReader(buf2, delimiter=delimiter)
        reader.fieldnames = headers_final

        rows = []
        for i, row in enumerate(reader, start=2):
            def g(k): return (row.get(k) or "").strip()
            nome = g("nome")
            if not nome:
                continue
            modelo = _norm_modelo(g("modelo"))
            rep    = _to_int_repasse(g("repasse"), 35)
            cxp = g("codigo_xp")
            cmb = g("codigo_mb")
            net_xp        = _to_float(g("net_xp"))
            net_xp_global = _to_float(g("net_xp_global"))
            net_mb        = _to_float(g("net_mb"))
            net_total     = net_xp + net_xp_global + net_mb

            rows.append({
                "nome": nome,
                "modelo": modelo,
                "repasse": rep,
                "codigo_xp": cxp or None,
                "codigo_mb": cmb or None,
                "net_xp": net_xp,
                "net_xp_global": net_xp_global,
                "net_mb": net_mb,
                "net_total": net_total,
            })
        return rows

    # --- XLSX ---
    if filename.endswith(".xlsx"):
        try:
            from openpyxl import load_workbook
        except Exception:
            raise RuntimeError("Dependência 'openpyxl' não encontrada. Instale-a para importar .xlsx.")

        wb = load_workbook(file_storage, data_only=True)
        ws = wb.active  # primeira planilha

        # ler cabeçalhos
        headers_raw = []
        for cell in ws[1]:
            headers_raw.append(str(cell.value or "").strip())
        headers_norm = [_norm_header(h) for h in headers_raw]
        headers_final = [_HEADER_MAP.get(h, h) for h in headers_norm]

        required = {"nome","modelo","repasse","codigo_xp","codigo_mb","net_xp","net_xp_global","net_mb"}
        present = set(headers_final)
        missing = [h for h in required if h not in present]
        if missing:
            raise ValueError("Template inválido. Faltam colunas: " + ", ".join(sorted(missing)))

        # índice por nome final
        idx = {h: i for i, h in enumerate(headers_final)}

        rows = []
        for r in ws.iter_rows(min_row=2, values_only=True):
            def gv(key):
                j = idx.get(key)
                return "" if j is None else ("" if r[j] is None else str(r[j]).strip())

            nome = gv("nome")
            if not nome:
                continue
            modelo = _norm_modelo(gv("modelo"))
            rep    = _to_int_repasse(gv("repasse"), 35)
            cxp = gv("codigo_xp")
            cmb = gv("codigo_mb")
            net_xp        = _to_float(gv("net_xp"))
            net_xp_global = _to_float(gv("net_xp_global"))
            net_mb        = _to_float(gv("net_mb"))
            net_total     = net_xp + net_xp_global + net_mb

            rows.append({
                "nome": nome,
                "modelo": modelo,
                "repasse": rep,
                "codigo_xp": cxp or None,
                "codigo_mb": cmb or None,
                "net_xp": net_xp,
                "net_xp_global": net_xp_global,
                "net_mb": net_mb,
                "net_total": net_total,
            })
        return rows

    raise ValueError("Formato não suportado. Envie .csv ou .xlsx.")

@clientes_bp.route('/importar/template.csv', methods=['GET'])
@login_required
def baixar_template_clientes():
    """Baixa um CSV de modelo para importação em massa."""
    csv_text = _make_template_csv()
    return current_app.response_class(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=template_importar_clientes.csv"
        },
    )

@clientes_bp.route('/importar/template.xlsx', methods=['GET'])
@login_required
def baixar_template_clientes_xlsx():
    """Baixa um XLSX de modelo para importação em massa."""
    xlsx_bytes = _make_template_xlsx()
    return current_app.response_class(
        xlsx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=template_importar_clientes.xlsx"
        },
    )

@clientes_bp.route('/importar', methods=['GET', 'POST'])
@login_required
def importar_em_massa():
    """
    GET  -> mostra a tela com botão de download do(s) template(s) e o upload do arquivo
    POST -> processa o arquivo (.csv ou .xlsx) e insere/upserta clientes do usuário
    """
    if request.method == "GET":
        return render_template("clientes/importar.html")

    # POST
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return redirect(url_for('clientes.index'))

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for('clientes.index'))

    f = request.files.get("arquivo")
    if not f or not (f.filename.lower().endswith(".csv") or f.filename.lower().endswith(".xlsx")):
        flash("Envie um arquivo .csv ou .xlsx no formato do template.", "error")
        return redirect(url_for("clientes.importar_em_massa"))

    try:
        rows = _parse_import_file(f)
        if not rows:
            flash("Nenhuma linha válida encontrada no arquivo.", "warning")
            return redirect(url_for("clientes.importar_em_massa"))

        # injeta user_id em todas as linhas
        rows = [{**r, "user_id": uid} for r in rows]

        # Estratégia:
        # - preferir UPSERT por (user_id, codigo_xp) quando houver codigo_xp
        # - e por (user_id, codigo_mb) quando houver apenas codigo_mb
        # observação: indices únicos (recomendados) permitem o on_conflict
        #   create unique index if not exists clientes_uid_cxp_uidx on public.clientes (user_id, codigo_xp);
        #   create unique index if not exists clientes_uid_cmb_uidx on public.clientes (user_id, codigo_mb);
        batch_xp = [r for r in rows if r.get("codigo_xp")]
        batch_mb = [r for r in rows if not r.get("codigo_xp") and r.get("codigo_mb")]
        batch_nk = [r for r in rows if not r.get("codigo_xp") and not r.get("codigo_mb")]  # sem chave -> INSERT

        CHUNK = 500

        # 1) upsert por (user_id, codigo_xp)
        for i in range(0, len(batch_xp), CHUNK):
            supabase.table("clientes").upsert(
                batch_xp[i:i+CHUNK],
                on_conflict="user_id,codigo_xp"
            ).execute()

        # 2) upsert por (user_id, codigo_mb)
        for i in range(0, len(batch_mb), CHUNK):
            supabase.table("clientes").upsert(
                batch_mb[i:i+CHUNK],
                on_conflict="user_id,codigo_mb"
            ).execute()

        # 3) inserts simples (sem código de chave) — evitamos sobrescrever nomes aleatoriamente
        for i in range(0, len(batch_nk), CHUNK):
            supabase.table("clientes").insert(batch_nk[i:i+CHUNK]).execute()

        flash(f"Importação concluída. Linhas processadas: {len(rows)}.", "success")
        return redirect(url_for("clientes.index"))

    except ValueError as ve:
        current_app.logger.info("Import clientes: arquivo inválido: %s", ve)
        flash(str(ve), "error")
    except Exception as e:
        current_app.logger.exception("Falha na importação de clientes: %s", e)
        flash("Falha ao importar clientes. Verifique o arquivo e tente novamente.", "error")

    return redirect(url_for("clientes.importar_em_massa"))

@clientes_bp.route('/supernova')
@login_required
def supernova():
    """Tela Supernova: lista clientes com nome e data da última supernova"""
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return render_template('clientes/supernova.html',
                             clientes_supernova=[],
                             filtros={"letra": ""},
                             letras_ordenadas=[])

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return render_template('clientes/supernova.html',
                             clientes_supernova=[],
                             filtros={"letra": ""},
                             letras_ordenadas=[])

    # ── filtros vindos da URL ──────────────────────────────────────────────
    letra_filter = (request.args.get('letra') or '').strip()        # primeira letra do nome
    urgencia_filter = (request.args.get('urgencia') or '').strip()  # nível de urgência
    mes_filter = (request.args.get('mes') or '').strip()            # mês da última supernova

    try:
        # Buscar todos os clientes do usuário
        res_clientes = supabase.table("clientes").select("id, nome").eq("user_id", uid).execute()
        clientes = res_clientes.data or []

        # Aplicar filtro por primeira letra do nome, se houver
        if letra_filter and letra_filter.upper() in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            letra_upper = letra_filter.upper()
            clientes = [
                c for c in clientes
                if (c.get("nome") or "").strip().upper().startswith(letra_upper)
            ]

        # Gerar lista de letras disponíveis (buscar todas as primeiras letras dos clientes)
        try:
            all_res = supabase.table("clientes").select("nome").eq("user_id", uid).execute()
            all_clientes = all_res.data or []
            letras_disponiveis = set()
            for c in all_clientes:
                nome = (c.get("nome") or "").strip()
                if nome:
                    primeira_letra = nome[0].upper()
                    if primeira_letra.isalpha():
                        letras_disponiveis.add(primeira_letra)
            letras_ordenadas = sorted(list(letras_disponiveis))
        except Exception:
            letras_ordenadas = []

        # 🚀 OTIMIZAÇÃO: Buscar TODAS as supernovas de uma vez (elimina N+1)
        supernovas_map = {}
        try:
            res_supernovas_all = (supabase.table("supernovas")
                                .select("cliente_id, data_supernova, observacoes")
                                .eq("user_id", uid)
                                .order("data_supernova", desc=True)
                                .execute())

            # Agrupar por cliente_id, mantendo apenas a mais recente
            for item in (res_supernovas_all.data or []):
                cliente_id = item.get('cliente_id')
                if cliente_id not in supernovas_map:
                    supernovas_map[cliente_id] = item
        except Exception as e:
            current_app.logger.debug("Erro ao buscar supernovas: %s", e)

        clientes_supernova = []
        for cliente in clientes:
            cliente_id = cliente.get('id')
            nome_cliente = cliente.get('nome', '')

            # Buscar do mapa (já carregado)
            supernova_record = supernovas_map.get(cliente_id)

            data_ultima_supernova = None
            observacoes_supernova = None

            if supernova_record:
                data_str = supernova_record.get('data_supernova')
                observacoes_supernova = supernova_record.get('observacoes')

                if data_str:
                    # Converter string para datetime se necessário
                    if isinstance(data_str, str):
                        # Remover timezone se presente e converter
                        data_str_clean = data_str.replace('Z', '').replace('+00:00', '')
                        try:
                            data_ultima_supernova = datetime.fromisoformat(data_str_clean)
                        except ValueError:
                            # Fallback para outros formatos
                            from dateutil import parser
                            data_ultima_supernova = parser.parse(data_str)
                    else:
                        data_ultima_supernova = data_str

            # Calcular urgência baseada na data da última supernova
            urgencia_flag = None
            dias_desde_supernova = None

            if data_ultima_supernova:
                hoje = datetime.now()
                # Se a supernova tem timezone, remover para comparação
                if hasattr(data_ultima_supernova, 'tzinfo') and data_ultima_supernova.tzinfo:
                    data_supernova_local = data_ultima_supernova.replace(tzinfo=None)
                else:
                    data_supernova_local = data_ultima_supernova

                diff = hoje - data_supernova_local
                dias_desde_supernova = diff.days

                if dias_desde_supernova > 90:  # Mais de 3 meses (90 dias)
                    urgencia_flag = 'critica'
                elif dias_desde_supernova > 60:  # Mais de 2 meses
                    urgencia_flag = 'alta'
                elif dias_desde_supernova > 30:  # Mais de 1 mês
                    urgencia_flag = 'media'
                else:
                    urgencia_flag = 'baixa'
            else:
                # Sem supernova = urgência crítica
                urgencia_flag = 'critica'
                dias_desde_supernova = None

            clientes_supernova.append({
                'id': cliente_id,
                'nome': nome_cliente,
                'data_ultima_supernova': data_ultima_supernova,
                'observacoes_supernova': observacoes_supernova,
                'urgencia_flag': urgencia_flag,
                'dias_desde_supernova': dias_desde_supernova
            })

        # Aplicar filtros pós-processamento
        clientes_filtrados = clientes_supernova

        # Filtro por urgência
        if urgencia_filter and urgencia_filter in ['critica', 'alta', 'media', 'baixa']:
            clientes_filtrados = [c for c in clientes_filtrados if c['urgencia_flag'] == urgencia_filter]

        # Filtro por mês da última supernova
        if mes_filter:
            try:
                mes_ano = mes_filter  # Formato esperado: 'YYYY-MM'
                if len(mes_ano) == 7 and '-' in mes_ano:  # Validar formato YYYY-MM
                    clientes_filtrados = [
                        c for c in clientes_filtrados
                        if c['data_ultima_supernova'] and c['data_ultima_supernova'].strftime('%Y-%m') == mes_ano
                    ]
            except Exception:
                current_app.logger.warning("Filtro de mês inválido: %s", mes_filter)

        # Ordenar por urgência (crítica primeiro) e depois por nome
        prioridade_urgencia = {'critica': 0, 'alta': 1, 'media': 2, 'baixa': 3}
        clientes_filtrados.sort(key=lambda x: (
            prioridade_urgencia.get(x['urgencia_flag'], 4),
            (x['nome'] or '').upper()
        ))

        clientes_supernova = clientes_filtrados

        return render_template('clientes/supernova.html',
                             clientes_supernova=clientes_supernova,
                             filtros={
                                 "letra": letra_filter,
                                 "urgencia": urgencia_filter,
                                 "mes": mes_filter
                             },
                             letras_ordenadas=letras_ordenadas)

    except Exception:
        current_app.logger.exception("Falha ao carregar dados da Supernova")
        flash("Falha ao carregar dados da Supernova.", "warning")
        return render_template('clientes/supernova.html',
                             clientes_supernova=[],
                             filtros={
                                 "letra": letra_filter,
                                 "urgencia": urgencia_filter,
                                 "mes": mes_filter
                             },
                             letras_ordenadas=[])

@clientes_bp.route('/supernova/salvar', methods=['POST'])
@login_required
def salvar_supernova():
    """Salva ou atualiza a data da supernova para um cliente"""
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return redirect(url_for('clientes.supernova'))

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for('clientes.supernova'))

    cliente_id = request.form.get('cliente_id')
    data_supernova_str = request.form.get('data_supernova')
    observacoes = request.form.get('observacoes', '').strip()

    if not cliente_id or not data_supernova_str:
        flash("Cliente e data da supernova são obrigatórios.", "error")
        return redirect(url_for('clientes.supernova'))

    try:
        # Verificar se o cliente pertence ao usuário atual
        res_cliente = (supabase.table("clientes")
                      .select("id, nome")
                      .eq("id", cliente_id)
                      .eq("user_id", uid)
                      .execute())

        if not res_cliente.data:
            flash("Cliente não encontrado ou sem permissão para editar.", "error")
            return redirect(url_for('clientes.supernova'))

        cliente_nome = res_cliente.data[0].get('nome', 'Cliente')

        # Converter string de data para datetime (apenas data, sem hora)
        try:
            # Se vier no formato YYYY-MM-DD (input type="date")
            if len(data_supernova_str) == 10 and '-' in data_supernova_str:
                data_supernova = datetime.strptime(data_supernova_str, '%Y-%m-%d')
            else:
                # Fallback para formatos com hora (compatibilidade)
                data_supernova = datetime.fromisoformat(data_supernova_str)

            current_app.logger.info("SUPERNOVA: Data convertida: %s", data_supernova)
        except ValueError as ve:
            current_app.logger.error("SUPERNOVA: Erro na conversão de data '%s': %s", data_supernova_str, ve)
            flash(f"Formato de data inválido: {data_supernova_str}", "error")
            return redirect(url_for('clientes.supernova'))

        # Primeiro, tentar criar a tabela se não existir
        try:
            # Verificar se já existe um registro de supernova para este cliente
            res_supernova_existente = (supabase.table("supernovas")
                                     .select("id")
                                     .eq("cliente_id", cliente_id)
                                     .eq("user_id", uid)
                                     .execute())

            current_app.logger.info("SUPERNOVA: Verificação existente OK - encontrados %d registros", len(res_supernova_existente.data or []))

        except Exception as table_error:
            current_app.logger.error("SUPERNOVA: Erro ao acessar tabela supernovas: %s", table_error)
            # Se a tabela não existe, vamos tentar criar o registro mesmo assim
            res_supernova_existente = type('MockResponse', (), {'data': []})()

        payload = {
            "cliente_id": cliente_id,
            "data_supernova": data_supernova.isoformat(),
            "observacoes": observacoes or None,
            "user_id": uid,  # Garantir que o registro pertence ao usuário
            "updated_at": datetime.now().isoformat()
        }

        current_app.logger.info("SUPERNOVA: Payload preparado: %s", payload)

        if res_supernova_existente.data:
            # Atualizar registro existente
            supernova_id = res_supernova_existente.data[0]["id"]
            current_app.logger.info("SUPERNOVA: Atualizando registro existente ID: %s", supernova_id)

            result = supabase.table("supernovas").update(payload).eq("id", supernova_id).execute()
            current_app.logger.info("SUPERNOVA: Update result: %s", result.data)

            flash(f"Data da supernova atualizada para {cliente_nome}.", "success")
            current_app.logger.info("SUPERNOVA: Atualizada para cliente %s (%s) by user %s", cliente_nome, cliente_id, uid)
        else:
            # Criar novo registro
            payload["created_at"] = datetime.now().isoformat()
            current_app.logger.info("SUPERNOVA: Criando novo registro para cliente %s", cliente_nome)

            result = supabase.table("supernovas").insert(payload).execute()
            current_app.logger.info("SUPERNOVA: Insert result: %s", result.data)

            flash(f"Data da supernova registrada para {cliente_nome}.", "success")
            current_app.logger.info("SUPERNOVA: Nova criada para cliente %s (%s) by user %s", cliente_nome, cliente_id, uid)

    except Exception as e:
        current_app.logger.exception("SUPERNOVA: Falha completa ao salvar supernova para cliente %s: %s", cliente_id, e)

        # Tentar dar mais detalhes sobre o erro
        error_msg = str(e)
        if "does not exist" in error_msg.lower():
            flash("Tabela de supernova não configurada no banco de dados. Contate o administrador.", "error")
        elif "permission" in error_msg.lower():
            flash("Sem permissão para salvar dados de supernova.", "error")
        elif "constraint" in error_msg.lower():
            flash("Erro de validação nos dados. Verifique os campos.", "error")
        else:
            flash(f"Erro ao salvar data da supernova: {error_msg}", "error")

    return redirect(url_for('clientes.supernova'))

@clientes_bp.route('/supernova/verificar-tabela')
@login_required
def verificar_tabela_supernova():
    """Rota administrativa para verificar/criar tabela supernovas"""
    supabase = _get_supabase()
    if not supabase:
        return {"erro": "Supabase indisponível"}, 500

    try:
        # Tentar fazer uma consulta simples na tabela
        result = supabase.table("supernovas").select("id").limit(1).execute()
        return {
            "sucesso": True,
            "tabela_existe": True,
            "registros_encontrados": len(result.data or []),
            "mensagem": "Tabela 'supernovas' existe e está acessível"
        }
    except Exception as e:
        error_msg = str(e)
        current_app.logger.error("VERIFICAR TABELA SUPERNOVA: %s", error_msg)

        sql_criar_tabela = """
        -- SQL para criar a tabela supernovas no Supabase
        CREATE TABLE IF NOT EXISTS public.supernovas (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            cliente_id UUID NOT NULL REFERENCES public.clientes(id) ON DELETE CASCADE,
            user_id UUID NOT NULL,
            data_supernova TIMESTAMP WITH TIME ZONE NOT NULL,
            observacoes TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        -- Índices para performance
        CREATE INDEX IF NOT EXISTS idx_supernovas_cliente_id ON public.supernovas(cliente_id);
        CREATE INDEX IF NOT EXISTS idx_supernovas_user_id ON public.supernovas(user_id);
        CREATE INDEX IF NOT EXISTS idx_supernovas_data ON public.supernovas(data_supernova);

        -- RLS (Row Level Security)
        ALTER TABLE public.supernovas ENABLE ROW LEVEL SECURITY;

        -- Política para usuários autenticados (Supabase não suporta IF NOT EXISTS em CREATE POLICY)
        DROP POLICY IF EXISTS "Users can manage their own supernovas" ON public.supernovas;
        CREATE POLICY "Users can manage their own supernovas"
        ON public.supernovas
        FOR ALL
        USING (auth.uid() = user_id::uuid);
        """

        return {
            "sucesso": False,
            "tabela_existe": False,
            "erro": error_msg,
            "sql_criar_tabela": sql_criar_tabela,
            "mensagem": "Tabela 'supernovas' não existe. Execute o SQL fornecido no Supabase."
        }, 400

# ----------------- Cross Sell -----------------
@clientes_bp.route('/cross-sell')
@login_required
def cross_sell():
    """Tela Cross Sell: gerencia apresentação e boletagem de produtos aos clientes"""
    import time
    start_time = time.time()

    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return render_template('clientes/cross_sell.html',
                             clientes_cross_sell=[],
                             filtros={"q": "", "letra": ""},
                             letras_ordenadas=[])

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return render_template('clientes/cross_sell.html',
                             clientes_cross_sell=[],
                             filtros={"q": "", "letra": ""},
                             letras_ordenadas=[])

    # Filtros
    q_txt = (request.args.get('q') or '').strip()
    letra_filter = (request.args.get('letra') or '').strip()

    try:
        t1 = time.time()
        current_app.logger.info("CROSS_SELL: Iniciando queries...")
        # Buscar todos os clientes do usuário
        query = supabase.table("clientes").select("id, nome, net_total").eq("user_id", uid)

        if q_txt:
            pattern = f"%{q_txt}%"
            try:
                query = query.ilike("nome", pattern)
            except:
                pass

        res_clientes = query.execute()
        clientes = res_clientes.data or []
        current_app.logger.info("CROSS_SELL: Clientes buscados em %.2fs (%d clientes)", time.time() - t1, len(clientes))

        # Aplicar filtro por primeira letra
        if letra_filter and letra_filter.upper() in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            letra_upper = letra_filter.upper()
            clientes = [
                c for c in clientes
                if (c.get("nome") or "").strip().upper().startswith(letra_upper)
            ]

        # Buscar TODOS os dados de cross sell de uma vez (otimização N+1)
        t2 = time.time()
        try:
            res_cross_all = supabase.table("cross_sell").select("*").eq("user_id", uid).execute()
            cross_sell_map = {item['cliente_id']: item for item in (res_cross_all.data or [])}
            current_app.logger.info("CROSS_SELL: Cross sell data buscado em %.2fs (%d registros)", time.time() - t2, len(cross_sell_map))
        except Exception as e:
            current_app.logger.debug("Erro ao buscar cross_sell: %s", e)
            cross_sell_map = {}

        # Montar lista de clientes com dados de cross sell
        clientes_cross_sell = []
        default_cross_data = {
            'fee_based': '',
            'financial_planning': '',
            'mb': '',
            'offshore': '',
            'produto_estruturado': '',
            'asset': '',
            'seguro_vida': '',
            'consorcio': '',
            'wealth': ''
        }

        for cliente in clientes:
            cliente_id = cliente.get('id')
            nome_cliente = cliente.get('nome', '')

            # Buscar dados do mapa (já carregado)
            cross_data = cross_sell_map.get(cliente_id, default_cross_data)

            clientes_cross_sell.append({
                'id': cliente_id,
                'nome': nome_cliente,
                'fee_based': cross_data.get('fee_based', ''),
                'financial_planning': cross_data.get('financial_planning', ''),
                'mb': cross_data.get('mb', ''),
                'offshore': cross_data.get('offshore', ''),
                'produto_estruturado': cross_data.get('produto_estruturado', ''),
                'asset': cross_data.get('asset', ''),
                'seguro_vida': cross_data.get('seguro_vida', ''),
                'consorcio': cross_data.get('consorcio', ''),
                'wealth': cross_data.get('wealth', '')
            })

        # Ordenar por nome
        clientes_cross_sell.sort(key=lambda x: (x['nome'] or '').upper())

        # Gerar lista de letras disponíveis (usar clientes já carregados)
        letras_disponiveis = set()
        for c in clientes:
            nome = (c.get("nome") or "").strip()
            if nome:
                primeira_letra = nome[0].upper()
                if primeira_letra.isalpha():
                    letras_disponiveis.add(primeira_letra)
        letras_ordenadas = sorted(list(letras_disponiveis))

        elapsed = time.time() - start_time
        current_app.logger.info("CROSS_SELL: Página carregada em %.2fs", elapsed)

        return render_template('clientes/cross_sell.html',
                             clientes_cross_sell=clientes_cross_sell,
                             filtros={"q": q_txt, "letra": letra_filter},
                             letras_ordenadas=letras_ordenadas)

    except Exception:
        current_app.logger.exception("Falha ao carregar dados de Cross Sell")
        flash("Falha ao carregar dados de Cross Sell.", "warning")
        return render_template('clientes/cross_sell.html',
                             clientes_cross_sell=[],
                             filtros={"q": q_txt, "letra": letra_filter},
                             letras_ordenadas=[])

@clientes_bp.route('/cross-sell/salvar', methods=['POST'])
@login_required
def salvar_cross_sell():
    """Salva ou atualiza os dados de cross sell para um cliente"""
    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return redirect(url_for('clientes.cross_sell'))

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return redirect(url_for('clientes.cross_sell'))

    cliente_id = request.form.get('cliente_id')

    if not cliente_id:
        flash("Cliente não identificado.", "error")
        return redirect(url_for('clientes.cross_sell'))

    try:
        # Verificar se o cliente pertence ao usuário atual
        res_cliente = (supabase.table("clientes")
                      .select("id, nome")
                      .eq("id", cliente_id)
                      .eq("user_id", uid)
                      .execute())

        if not res_cliente.data:
            flash("Cliente não encontrado ou sem permissão para editar.", "error")
            return redirect(url_for('clientes.cross_sell'))

        cliente_nome = res_cliente.data[0].get('nome', 'Cliente')

        # Coletar dados do formulário
        payload = {
            "cliente_id": cliente_id,
            "user_id": uid,
            "fee_based": request.form.get('fee_based', ''),
            "financial_planning": request.form.get('financial_planning', ''),
            "mb": request.form.get('mb', ''),
            "offshore": request.form.get('offshore', ''),
            "produto_estruturado": request.form.get('produto_estruturado', ''),
            "asset": request.form.get('asset', ''),
            "seguro_vida": request.form.get('seguro_vida', ''),
            "consorcio": request.form.get('consorcio', ''),
            "wealth": request.form.get('wealth', ''),
            "updated_at": datetime.now().isoformat()
        }

        # Verificar se já existe um registro
        res_existente = (supabase.table("cross_sell")
                        .select("id")
                        .eq("cliente_id", cliente_id)
                        .eq("user_id", uid)
                        .execute())

        if res_existente.data:
            # Atualizar
            cross_sell_id = res_existente.data[0]["id"]
            supabase.table("cross_sell").update(payload).eq("id", cross_sell_id).execute()
            flash(f"Cross Sell atualizado para {cliente_nome}.", "success")
        else:
            # Inserir
            payload["created_at"] = datetime.now().isoformat()
            supabase.table("cross_sell").insert(payload).execute()
            flash(f"Cross Sell registrado para {cliente_nome}.", "success")

    except Exception as e:
        current_app.logger.exception("Falha ao salvar cross sell: %s", e)
        flash(f"Erro ao salvar Cross Sell: {str(e)}", "error")

    return redirect(url_for('clientes.cross_sell'))

# ----------------- Insights -----------------
@clientes_bp.route('/insights')
@login_required
def insights():
    """Tela Insights: cruzamento de dados para insights valiosos"""
    import time
    start_time = time.time()

    supabase = _get_supabase()
    if not supabase:
        flash("Supabase indisponível.", "warning")
        return render_template('clientes/insights.html', insights=[])

    uid = _uid()
    if not uid:
        flash("Sessão inválida: não foi possível identificar o usuário.", "error")
        return render_template('clientes/insights.html', insights=[])

    try:
        # Buscar todos os dados necessários
        t1 = time.time()
        res_clientes = supabase.table("clientes").select("*").eq("user_id", uid).execute()
        clientes = res_clientes.data or []
        current_app.logger.info("INSIGHTS: Clientes buscados em %.2fs (%d clientes)", time.time() - t1, len(clientes))

        # Buscar dados de cross_sell
        t2 = time.time()
        res_cross = supabase.table("cross_sell").select("*").eq("user_id", uid).execute()
        cross_sell_data = {item['cliente_id']: item for item in (res_cross.data or [])}
        current_app.logger.info("INSIGHTS: Cross sell buscado em %.2fs (%d registros)", time.time() - t2, len(cross_sell_data))

        insights_list = []

        # === INSIGHT 1: Clientes com NET > 1M sem Financial Planning ===
        clientes_alto_net_sem_fp = []
        for cliente in clientes:
            net_total = (_to_float(cliente.get('net_total')) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(cliente.get('net_total'))
            if net_total >= 1000000:
                cross = cross_sell_data.get(cliente['id'], {})
                fp_status = cross.get('financial_planning', '')
                if fp_status != 'Apresentado' and fp_status != 'Boletado':
                    clientes_alto_net_sem_fp.append({
                        'nome': cliente.get('nome'),
                        'net_total': net_total
                    })

        if clientes_alto_net_sem_fp:
            insights_list.append({
                'tipo': 'oportunidade',
                'titulo': f'🎯 {len(clientes_alto_net_sem_fp)} clientes com NET > R$ 1M sem Financial Planning',
                'descricao': f'Há {len(clientes_alto_net_sem_fp)} clientes com patrimônio acima de R$ 1 milhão que ainda não tiveram Financial Planning apresentado.',
                'clientes': clientes_alto_net_sem_fp,
                'prioridade': 'alta'
            })

        # === INSIGHT 2: Clientes TRADICIONAL com NET > 500K (candidatos a Fee Based) ===
        clientes_tradicional_candidatos_fee = []
        for cliente in clientes:
            modelo = _norm_modelo(cliente.get('modelo'))
            net_total = (_to_float(cliente.get('net_total')) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(cliente.get('net_total'))
            if modelo == 'TRADICIONAL' and net_total >= 500000:
                cross = cross_sell_data.get(cliente['id'], {})
                fee_status = cross.get('fee_based', '')
                if fee_status != 'Apresentado' and fee_status != 'Boletado':
                    clientes_tradicional_candidatos_fee.append({
                        'nome': cliente.get('nome'),
                        'net_total': net_total
                    })

        if clientes_tradicional_candidatos_fee:
            insights_list.append({
                'tipo': 'conversao',
                'titulo': f'💡 {len(clientes_tradicional_candidatos_fee)} clientes TRADICIONAL com NET > R$ 500K',
                'descricao': f'{len(clientes_tradicional_candidatos_fee)} clientes no modelo TRADICIONAL com patrimônio acima de R$ 500 mil são fortes candidatos para migração ao modelo Fee Based.',
                'clientes': clientes_tradicional_candidatos_fee,
                'prioridade': 'alta'
            })

        # === INSIGHT 3: Clientes sem Offshore com NET > 1M ===
        clientes_sem_offshore = []
        for cliente in clientes:
            net_total = (_to_float(cliente.get('net_total')) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(cliente.get('net_total'))
            if net_total >= 1000000:
                cross = cross_sell_data.get(cliente['id'], {})
                offshore_status = cross.get('offshore', '')
                if offshore_status != 'Apresentado' and offshore_status != 'Boletado':
                    clientes_sem_offshore.append({
                        'nome': cliente.get('nome'),
                        'net_total': net_total
                    })

        if clientes_sem_offshore:
            insights_list.append({
                'tipo': 'oportunidade',
                'titulo': f'🌎 {len(clientes_sem_offshore)} clientes com NET > R$ 1M sem Offshore',
                'descricao': f'{len(clientes_sem_offshore)} clientes com patrimônio acima de R$ 1 milhão ainda não tiveram soluções Offshore apresentadas.',
                'clientes': clientes_sem_offshore,
                'prioridade': 'alta'
            })

        # === INSIGHT 4: Clientes com NET > 3M sem Asset apresentado ===
        clientes_alto_net_sem_asset = []
        for cliente in clientes:
            net_total = (_to_float(cliente.get('net_total')) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(cliente.get('net_total'))
            if net_total >= 3000000:
                cross = cross_sell_data.get(cliente['id'], {})
                asset_status = cross.get('asset', '')
                if asset_status != 'Apresentado' and asset_status != 'Boletado':
                    clientes_alto_net_sem_asset.append({
                        'nome': cliente.get('nome'),
                        'net_total': net_total
                    })

        if clientes_alto_net_sem_asset:
            insights_list.append({
                'tipo': 'oportunidade',
                'titulo': f'💎 {len(clientes_alto_net_sem_asset)} clientes com NET > R$ 3M sem Asset apresentado',
                'descricao': f'{len(clientes_alto_net_sem_asset)} clientes com patrimônio acima de R$ 3 milhões ainda não tiveram o modelo Asset apresentado.',
                'clientes': clientes_alto_net_sem_asset,
                'prioridade': 'alta'
            })

        # === INSIGHT 5: Clientes sem Seguro de Vida (todos com NET > 300K) ===
        clientes_sem_seguro = []
        for cliente in clientes:
            net_total = (_to_float(cliente.get('net_total')) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(cliente.get('net_total'))
            if net_total >= 300000:
                cross = cross_sell_data.get(cliente['id'], {})
                seguro_status = cross.get('seguro_vida', '')
                if seguro_status != 'Apresentado' and seguro_status != 'Boletado':
                    clientes_sem_seguro.append({
                        'nome': cliente.get('nome'),
                        'net_total': net_total
                    })

        if clientes_sem_seguro:
            insights_list.append({
                'tipo': 'protecao',
                'titulo': f'🛡️ {len(clientes_sem_seguro)} clientes com NET > R$ 300K sem Seguro de Vida',
                'descricao': f'{len(clientes_sem_seguro)} clientes com patrimônio significativo ainda não têm Seguro de Vida apresentado.',
                'clientes': clientes_sem_seguro,
                'prioridade': 'media'
            })

        # === INSIGHT 6: Distribuição de modelos (estatística) ===
        distribuicao_modelos = {}
        total_net_por_modelo = {}
        for cliente in clientes:
            modelo = _norm_modelo(cliente.get('modelo'))
            net_total = (_to_float(cliente.get('net_total')) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(cliente.get('net_total'))
            distribuicao_modelos[modelo] = distribuicao_modelos.get(modelo, 0) + 1
            total_net_por_modelo[modelo] = total_net_por_modelo.get(modelo, 0) + net_total

        modelo_mais_comum = max(distribuicao_modelos.items(), key=lambda x: x[1]) if distribuicao_modelos else None
        if modelo_mais_comum:
            insights_list.append({
                'tipo': 'estatistica',
                'titulo': f'📈 Distribuição de Modelos: {modelo_mais_comum[0]} lidera com {modelo_mais_comum[1]} clientes',
                'descricao': f'Seu modelo mais comum é {modelo_mais_comum[0]} com {modelo_mais_comum[1]} clientes. NET total neste modelo: R$ {total_net_por_modelo.get(modelo_mais_comum[0], 0):,.2f}',
                'clientes': [],
                'prioridade': 'info'
            })

        # === INSIGHT 7: Clientes com MB não apresentado ===
        clientes_sem_mb = []
        for cliente in clientes:
            codigo_mb = (cliente.get('codigo_mb') or '').strip()
            if not codigo_mb:  # Cliente não tem código MB
                cross = cross_sell_data.get(cliente['id'], {})
                mb_status = cross.get('mb', '')
                if mb_status != 'Apresentado' and mb_status != 'Boletado':
                    net_total = (_to_float(cliente.get('net_total')) / 100.0) if NET_TOTAL_IN_CENTS else _to_float(cliente.get('net_total'))
                    if net_total >= 100000:  # Só clientes com NET significativo
                        clientes_sem_mb.append({
                            'nome': cliente.get('nome'),
                            'net_total': net_total
                        })

        if clientes_sem_mb:
            insights_list.append({
                'tipo': 'expansao',
                'titulo': f'🏦 {len(clientes_sem_mb)} clientes sem MB (NET > R$ 100K)',
                'descricao': f'{len(clientes_sem_mb)} clientes com patrimônio acima de R$ 100 mil ainda não têm conta MB. Oportunidade de expansão.',
                'clientes': clientes_sem_mb,
                'prioridade': 'media'
            })

        # Ordenar insights por prioridade
        prioridade_ordem = {'alta': 0, 'media': 1, 'info': 2}
        insights_list.sort(key=lambda x: prioridade_ordem.get(x['prioridade'], 3))

        elapsed = time.time() - start_time
        current_app.logger.info("INSIGHTS: Página carregada em %.2fs (%d insights)", elapsed, len(insights_list))

        return render_template('clientes/insights.html', insights=insights_list)

    except Exception:
        current_app.logger.exception("Falha ao gerar insights")
        flash("Falha ao gerar insights.", "warning")
        return render_template('clientes/insights.html', insights=[])
