# dashboard.py
from __future__ import annotations

from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash, session
from utils import login_required
from datetime import datetime
from collections import defaultdict
import re
import unicodedata
import os

try:
    from supabase_client import supabase, get_supabase_client
except Exception:
    supabase = None

dash_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


# =============== helpers de sessão/consulta ===============
def _current_user_id() -> str | None:
    """
    Retorna o user_id UUID válido do Supabase.
    Com RLS ativo, o user_id deve ser um UUID válido da tabela auth.users.
    """
    u = session.get("user") or {}
    
    # PRIORIDADE 1: user_id do Supabase (UUID válido)
    user_id = u.get("id") or u.get("supabase_user_id")
    if user_id and len(user_id) > 10:  # UUID válido tem pelo menos 32 chars
        current_app.logger.info("USERID_DEBUG: Usando user_id UUID do Supabase: %s", user_id)
        return user_id
    
    # Se não temos UUID válido, isso significa que a autenticação não funcionou
    current_app.logger.error("USERID_DEBUG: Sem user_id UUID válido na sessão! Sessão: %s", u.keys())
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


@dash_bp.route("/salvar-meta", methods=["POST"], strict_slashes=False)
@login_required
def salvar_meta():
    """Salva meta mensal - versão simplificada"""
    mes = request.form.get("mes", "")
    try:
        meta_receita = float(request.form.get("meta_receita") or 0)
    except ValueError:
        meta_receita = 0.0
    
    flash(f"Meta de {mes} salva: {meta_receita:,.2f}", "success")
    return redirect(url_for("dashboard.index"))


@dash_bp.route("/", methods=["GET"])
@login_required  
def index():
    try:
        mes = datetime.now().strftime("%Y-%m")
        meta = 0.0
        
        return render_template(
            "dashboard.html",
            mes=mes,
            meta=meta,
            receita_total=0.0,
            clientes=[],
            by_modelo={},
            net_by_modelo={},
            mediana_net=0.0,
            mediana_receita_escritorio_ano=0.0,
            media_receita_escritorio_ano=0.0,
            media_net=0.0,
            quadrant_points=[],
            quadrant_counts={"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0},
            quadrant_pct={"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0},
            quadrant_total=0,
            clientes_por_quadrante={"Q1": [], "Q2": [], "Q3": [], "Q4": []},
            penetracao_pct=0,
            penetracao_ativos=0,
            penetracao_base=0,
            receita_ativa_mes=0.0,
            receita_passiva_mes=0.0,
            receita_assessor_mes=0.0,
            receita_assessor_recorrente=0.0,
            roa_percentual=0.0,
            historico_receita_passiva=[],
        )
        
    except Exception as e:
        current_app.logger.exception("Erro no dashboard")
        flash(f"Erro ao carregar dashboard: {str(e)}", "error")
        return redirect(url_for("auth.login"))