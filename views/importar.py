from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from utils import login_required
from services.finadvisor import parse_finadvisor_file
from datetime import datetime
import re

# Supabase obrigatório
try:
    from supabase_client import supabase
except Exception:
    supabase = None

importar_bp = Blueprint('importar', __name__, url_prefix='/importar-finadvisor')

# Colunas existentes em public.receita_itens
ALLOWED_COLS = {
    "data_ref",
    "cliente_codigo",
    "origem",
    "familia",
    "produto",
    "detalhe",
    "valor_bruto",
    "imposto_pct",
    "valor_liquido",
    "comissao_bruta",
    "comissao_liquida",
    "comissao_escritorio",
}

def _digits_only(s: str) -> str:
    if not s:
        return ""
    return "".join(re.findall(r"\d+", str(s)))

def _norm(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())

def _supabase_required_or_error():
    if not supabase:
        raise RuntimeError("Supabase não está configurado neste ambiente.")

# --- MB: manter o código MB, extraindo do Detalhe --------------------------------
_MB_DET_PATTERN = re.compile(r"cliente\s+(\d+)\s+ativo", flags=re.I)

def _fix_mercado_bitcoin_keep_mb(rows: list[dict]) -> None:
    """
    Para itens do produto 'Mercado Bitcoin', mantém o código MB:
    lê o número entre 'Cliente' e 'Ativo' na coluna 'detalhe' do CSV e
    grava esse número (somente dígitos) em 'cliente_codigo'.
    NÃO converte para XP.
    """
    if not rows:
        return
    for r in rows:
        if _norm(r.get("produto")) != "mercado bitcoin":
            continue
        m = _MB_DET_PATTERN.search(r.get("detalhe") or "")
        if m:
            r["cliente_codigo"] = m.group(1)  # MB “como está” (apenas dígitos)

def _row_sanitize_to_table(row: dict) -> dict:
    """Mantém apenas colunas da tabela e evita string vazia em cliente_codigo."""
    clean = {k: row.get(k) for k in ALLOWED_COLS}
    if clean.get("cliente_codigo") == "":
        clean["cliente_codigo"] = None
    return clean

# ----------------- View -----------------
@importar_bp.route('/', methods=['GET', 'POST'])
@login_required
def importar():
    if request.method == 'POST':
        competencia = (request.form.get('competencia') or '').strip()
        if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', competencia):
            flash('Informe a competência no formato YYYY-MM.', 'error')
            return redirect(url_for('importar.importar'))

        f = request.files.get('arquivo')
        if not f or f.filename == '':
            flash('Selecione um arquivo .xlsx ou .csv do FinAdvisor.', 'error')
            return redirect(url_for('importar.importar'))

        try:
            _supabase_required_or_error()

            # 🔑 user_id do dono (usado no DELETE e no INSERT)
            u = session.get("user") or {}
            uid = u.get("id") or u.get("supabase_user_id")
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for('importar.importar'))

            # 1) Parser (CSV/XLSX) -> linhas no formato da tabela
            rows = parse_finadvisor_file(f, data_ref=competencia)

            # 2) Mercado Bitcoin: manter MB (cliente_codigo = número do Detalhe)
            _fix_mercado_bitcoin_keep_mb(rows)

            # 3) Sanitização final
            rows_clean = [_row_sanitize_to_table(r) for r in rows]

            # 3.1) Anexar user_id a cada linha
            rows_clean_uid = [{**r, "user_id": uid} for r in rows_clean]

            # 4) Persistência no Supabase (idempotente por competência e dono)
            #    ⚠️ Filtra também por user_id para não apagar dados de outros usuários.
            supabase.table("receita_itens").delete().eq("data_ref", competencia).eq("user_id", uid).execute()

            CHUNK = 500
            for i in range(0, len(rows_clean_uid), CHUNK):
                supabase.table("receita_itens").insert(rows_clean_uid[i:i+CHUNK]).execute()

            tot_escr = sum((r.get("comissao_escritorio") or 0) for r in rows_clean_uid)
            tot_ass  = sum((r.get("valor_liquido") or 0) for r in rows_clean_uid)
            current_app.logger.info(
                "[Import %s uid=%s] linhas=%s | escr=%.2f | ass=%.2f | Supabase OK",
                competencia, uid, len(rows_clean_uid), tot_escr, tot_ass
            )
            flash(f'Importados {len(rows_clean_uid)} itens no Supabase para {competencia}.', 'success')
            return redirect(url_for('finadvisor.index', mes=competencia))

        except Exception as e:
            current_app.logger.exception("Erro ao importar FinAdvisor (Supabase only): %s", e)
            flash(f'Erro ao importar para o Supabase: {e}', 'error')
            return redirect(url_for('importar.importar'))

    default_month = datetime.today().strftime('%Y-%m')
    return render_template('importar.html', default_month=default_month)
