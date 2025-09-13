from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from utils import login_required
from models import db  # fallback local opcional
# (Opcional) se você tiver modelos locais para Produto/Alocacao/Cliente, pode importar
try:
    from models import Cliente, Produto, Alocacao
except Exception:
    Cliente = Produto = Alocacao = None

# Supabase opcional (não quebra se não estiver configurado)
try:
    from supabase_client import supabase
except Exception:
    supabase = None

alocacoes_bp = Blueprint("alocacoes", __name__, url_prefix="/alocacoes")


# ---------------- Helpers ----------------
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
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        current_app.logger.warning("Valor float inválido: %r", x)
        return 0.0


def _norm_modelo(v: str) -> str:
    if not v:
        return ""
    return str(v).strip().upper().replace(" ", "_")


def _norm_classe(v: str) -> str:
    if not v:
        return ""
    return str(v).strip().upper()


def _receita_base(valor: float, roa_pct: float) -> float:
    return float(valor) * (float(roa_pct) / 100.0)


def _pode_ter_receita_escritorio(modelo: str, classe: str) -> bool:
    m = _norm_modelo(modelo)
    c = _norm_classe(classe)

    ALLOWED_FB = {
        "RENDA FIXA DIGITAL", "OFFSHORE", "SEGURO DE VIDA", "CONSÓRCIO", "CONSORCIO"
    }
    ALLOWED_FB_SRV = ALLOWED_FB | {"PRODUTO ESTRUTURADO", "RENDA VARIÁVEL (MESA)", "RENDA VARIAVEL (MESA)"}

    if m == "FEE_BASED":
        return c in ALLOWED_FB
    if m == "FEE_BASED_SEM_RV":
        return c in ALLOWED_FB_SRV
    return True


def _calc_receitas(valor: float, roa_pct: float, repasse: int, modelo: str, classe: str):
    base = _receita_base(valor, roa_pct)
    if not _pode_ter_receita_escritorio(modelo, classe):
        return 0.0, 0.0, base
    
    # Para Renda Fixa Digital, sempre usar repasse fixo de 50%
    classe_norm = _norm_classe(classe)
    if classe_norm == "RENDA FIXA DIGITAL":
        rep = 0.5
    else:
        rep = 0.5 if int(repasse) == 50 else 0.35
    
    receita_escritorio = base
    receita_assessor = receita_escritorio * 0.80 * rep
    return receita_escritorio, receita_assessor, base


def _uid():
    u = session.get("user") or {}
    return u.get("id") or u.get("supabase_user_id")


def _carregar_clientes_produtos():
    clientes, produtos = [], []
    uid = _uid()
    if supabase:
        try:
            cres = supabase.table("clientes").select("id, nome").order("nome")
            if uid:
                cres = cres.eq("user_id", uid)
            else:
                # FAIL-CLOSED: Sem user_id válido, não retorna clientes
                clientes = []
                return clientes, []
            clientes = (cres.execute().data or [])
        except Exception:
            current_app.logger.exception("Falha ao carregar clientes do Supabase")
            clientes = []
        try:
            pres = supabase.table("produtos").select("id, nome, classe").order("nome")
            if uid:
                pres = pres.eq("user_id", uid)
            else:
                # FAIL-CLOSED: Sem user_id válido, não retorna produtos
                produtos = []
                return clientes, produtos
            produtos = (pres.execute().data or [])
        except Exception:
            current_app.logger.exception("Falha ao carregar produtos do Supabase")
            produtos = []
    elif Cliente and Produto:
        try:
            clientes = db.session.query(Cliente).order_by(Cliente.nome).all()
        except Exception:
            clientes = []
        try:
            produtos = db.session.query(Produto).order_by(Produto.nome).all()
        except Exception:
            produtos = []
    return clientes, produtos


def _get_alocacao_by_id(aloc_id: str):
    if supabase:
        try:
            uid = _uid()
            q = supabase.table("alocacoes").select(
                "id, cliente_id, produto_id, valor, percentual, efetivada, status, "
                "cliente:cliente_id ( id, nome, modelo, repasse ), "
                "produto:produto_id ( id, nome, classe, roa_pct, em_campanha, campanha_mes )"
            ).eq("id", aloc_id).limit(1)
            if uid:
                q = q.eq("user_id", uid)
            res = q.execute()
            data = (res.data or [])
            if data:
                r = data[0]
                return {
                    "id": r.get("id"),
                    "cliente_id": r.get("cliente_id"),
                    "produto_id": r.get("produto_id"),
                    "valor": _to_float(r.get("valor")),
                    "percentual": _to_float(r.get("percentual")),
                    "efetivada": bool(r.get("efetivada")),
                    "status": r.get("status") or "mapeado",
                    "cliente": r.get("cliente") or {},
                    "produto": r.get("produto") or {},
                }
        except Exception:
            current_app.logger.exception("Falha ao carregar alocação no Supabase")
            return None

    if Alocacao:
        try:
            a = db.session.get(Alocacao, aloc_id)
            if not a:
                return None
            c = db.session.get(Cliente, getattr(a, "cliente_id", None)) if Cliente else None
            p = db.session.get(Produto, getattr(a, "produto_id", None)) if Produto else None
            return {
                "id": getattr(a, "id", aloc_id),
                "cliente_id": getattr(a, "cliente_id", None),
                "produto_id": getattr(a, "produto_id", None),
                "valor": _to_float(getattr(a, "valor", 0)),
                "percentual": _to_float(getattr(a, "percentual", 0)),
                "efetivada": bool(getattr(a, "efetivada", False)) if hasattr(a, "efetivada") else False,
                "status": getattr(a, "status", "mapeado") if hasattr(a, "status") else "mapeado",
                "cliente": {
                    "id": getattr(c, "id", None),
                    "nome": getattr(c, "nome", "") if c else "",
                    "modelo": getattr(c, "modelo", "") if c else "",
                    "repasse": getattr(c, "repasse", 35) if c else 35,
                } if c else {},
                "produto": {
                    "id": getattr(p, "id", None),
                    "nome": getattr(p, "nome", "") if p else "",
                    "classe": getattr(p, "classe", None) if p else None,
                    "roa_pct": getattr(p, "roa_pct", None) if p else None,
                    "em_campanha": getattr(p, "em_campanha", False) if p else False,
                    "campanha_mes": getattr(p, "campanha_mes", None) if p else None,
                } if p else {},
            }
        except Exception:
            current_app.logger.exception("Falha ao carregar alocação no banco local")
            return None

    return None


# ---------------- LISTAGEM ----------------
@alocacoes_bp.route("/")
@login_required
def index():
    cliente_id_filter = (request.args.get("cliente_id") or "").strip() or None

    alocacoes = []
    if supabase:
        try:
            uid = _uid()
            q = supabase.table("alocacoes").select(
                "id, percentual, valor, cliente_id, produto_id, efetivada, status, "
                "cliente:cliente_id ( id, nome, modelo, repasse ), "
                "produto:produto_id ( id, nome, classe, roa_pct, em_campanha, campanha_mes )"
            ).order("created_at", desc=False)
            if uid:
                q = q.eq("user_id", uid)
            if cliente_id_filter:
                q = q.eq("cliente_id", cliente_id_filter)
            res = q.execute()
            for r in res.data or []:
                alocacoes.append({
                    "id": r.get("id"),
                    "percentual": _to_float(r.get("percentual")),
                    "valor": _to_float(r.get("valor")),
                    "cliente_id": r.get("cliente_id"),
                    "produto_id": r.get("produto_id"),
                    "efetivada": bool(r.get("efetivada")),
                    "status": r.get("status") or "mapeado",
                    "cliente": (r.get("cliente") or {}),
                    "produto": (r.get("produto") or {}),
                })
        except Exception:
            current_app.logger.exception("Falha ao listar alocações no Supabase")
            alocacoes = []
    elif Alocacao and Cliente and Produto:
        try:
            qs = (
                db.session.query(Alocacao, Cliente, Produto)
                .join(Cliente, Alocacao.cliente_id == Cliente.id)
                .join(Produto, Alocacao.produto_id == Produto.id)
                .order_by(Cliente.nome, Produto.nome)
            )
            if cliente_id_filter:
                qs = qs.filter(Alocacao.cliente_id == cliente_id_filter)
            for a, c, p in qs.all():
                alocacoes.append({
                    "id": getattr(a, "id", None),
                    "percentual": _to_float(getattr(a, "percentual", 0)),
                    "valor": _to_float(getattr(a, "valor", 0)),
                    "cliente_id": getattr(a, "cliente_id", None),
                    "produto_id": getattr(a, "produto_id", None),
                    "efetivada": bool(getattr(a, "efetivada", False)) if hasattr(a, "efetivada") else False,
                    "status": getattr(a, "status", "mapeado") if hasattr(a, "status") else "mapeado",
                    "cliente": {
                        "id": getattr(c, "id", None),
                        "nome": getattr(c, "nome", ""),
                        "modelo": getattr(c, "modelo", ""),
                        "repasse": getattr(c, "repasse", 35),
                    },
                    "produto": {
                        "id": getattr(p, "id", None),
                        "nome": getattr(p, "nome", ""),
                        "classe": getattr(p, "classe", None),
                        "roa_pct": getattr(p, "roa_pct", None),
                        "em_campanha": getattr(p, "em_campanha", False),
                        "campanha_mes": getattr(p, "campanha_mes", None),
                    },
                })
        except Exception:
            current_app.logger.exception("Falha ao listar alocações no banco local")
            alocacoes = []
    else:
        alocacoes = []

    total_geral = 0.0
    total_rec_escritorio = 0.0
    total_rec_assessor = 0.0
    by_cliente = {}
    by_produto = {}

    enriched = []
    for a in alocacoes:
        valor = _to_float(a.get("valor"))
        cliente = a.get("cliente") or {}
        produto = a.get("produto") or {}

        modelo = cliente.get("modelo") or ""
        repasse = cliente.get("repasse") or 35
        classe = produto.get("classe") or ""
        roa_pct = _to_float(produto.get("roa_pct"))

        rec_escr, rec_ass, rec_base = _calc_receitas(valor, roa_pct, repasse, modelo, classe)

        total_geral += valor
        total_rec_escritorio += rec_escr
        total_rec_assessor += rec_ass

        cid, cnome = cliente.get("id"), cliente.get("nome") or ""
        pid, pnome = produto.get("id"), produto.get("nome") or ""
        if cid:
            acc = by_cliente.setdefault(cid, {"nome": cnome, "valor": 0.0})
            acc["valor"] += valor
        if pid:
            acc = by_produto.setdefault(pid, {"nome": pnome, "valor": 0.0})
            acc["valor"] += valor

        b = dict(a)
        b["receita_base"] = rec_base
        b["receita_escritorio"] = rec_escr
        b["receita_assessor"] = rec_ass
        b["repasse"] = repasse
        enriched.append(b)

    totais_clientes = sorted(by_cliente.values(), key=lambda x: x["valor"], reverse=True)
    totais_produtos = sorted(by_produto.values(), key=lambda x: x["valor"], reverse=True)

    # Organizar alocações por status para o kanban
    kanban = {
        "mapeado": [],
        "apresentado": [],
        "push_enviado": [],
        "confirmado": []
    }
    
    for a in enriched:
        status = a.get("status", "mapeado")
        # Garantir que status seja válido, senão usar "mapeado"
        if status not in ["mapeado", "apresentado", "push_enviado", "confirmado"]:
            status = "mapeado"
            a["status"] = status
        kanban[status].append(a)

    return render_template(
        "alocacoes/index.html",
        alocacoes=enriched,
        kanban=kanban,
        total_geral=total_geral,
        totais_clientes=totais_clientes,
        totais_produtos=totais_produtos,
        total_rec_escritorio=total_rec_escritorio,
        total_rec_assessor=total_rec_assessor,
        cliente_id_filter=cliente_id_filter,
    )


# ---------------- LISTAGEM POR CLIENTE (atalho) ----------------
@alocacoes_bp.route("/cliente/<string:cliente_id>")
@login_required
def por_cliente(cliente_id: str):
    return redirect(url_for("alocacoes.index", cliente_id=cliente_id))


# ---------------- NOVA ALOCAÇÃO ----------------
@alocacoes_bp.route("/novo", methods=["GET", "POST"])
@login_required
def novo():
    if request.method == "POST":
        cliente_id = (request.form.get("cliente_id") or "").strip()
        produto_id = (request.form.get("produto_id") or "").strip()
        valor = _to_float(request.form.get("valor"))

        if not cliente_id or not produto_id:
            flash("Selecione cliente e produto.", "error")
            return redirect(url_for("alocacoes.novo"))

        if supabase:
            try:
                uid = _uid()
                if not uid:
                    flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                    return redirect(url_for("alocacoes.novo"))

                supabase.table("alocacoes").insert({
                    "cliente_id": cliente_id,
                    "produto_id": produto_id,
                    "valor": valor,
                    "percentual": 0,
                    "efetivada": False,
                    "status": "mapeado",
                    "user_id": uid,
                }).execute()
                flash("Alocação cadastrada.", "success")
                return redirect(url_for("alocacoes.index", cliente_id=cliente_id))
            except Exception:
                current_app.logger.exception("Falha ao inserir alocação no Supabase")
                flash("Falha ao cadastrar alocação no Supabase.", "error")

        if Alocacao:
            try:
                uid = _uid()
                if not uid:
                    flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                    return redirect(url_for("alocacoes.novo"))
                
                kwargs = {"cliente_id": cliente_id, "produto_id": produto_id}
                if hasattr(Alocacao, "user_id"):
                    kwargs["user_id"] = uid
                if hasattr(Alocacao, "valor"):
                    kwargs["valor"] = valor
                if hasattr(Alocacao, "percentual"):
                    kwargs.setdefault("percentual", 0)
                if hasattr(Alocacao, "efetivada"):
                    kwargs.setdefault("efetivada", False)
                if hasattr(Alocacao, "status"):
                    kwargs.setdefault("status", "mapeado")
                a = Alocacao(**kwargs)
                db.session.add(a)
                db.session.commit()
                flash("Alocação cadastrada (banco local).", "success")
                return redirect(url_for("alocacoes.index", cliente_id=cliente_id))
            except Exception:
                current_app.logger.exception("Falha ao inserir alocação no banco local")
                flash("Falha ao cadastrar alocação no banco local.", "error")

        return redirect(url_for("alocacoes.novo"))

    clientes, produtos = _carregar_clientes_produtos()
    return render_template("alocacoes/novo.html", clientes=clientes, produtos=produtos)


# ---------------- EDITAR ALOCAÇÃO ----------------
@alocacoes_bp.route("/<string:aloc_id>/editar", methods=["GET", "POST"])
@login_required
def editar(aloc_id: str):
    registro = _get_alocacao_by_id(aloc_id)
    if not registro:
        flash("Alocação não encontrada.", "error")
        return redirect(url_for("alocacoes.index"))

    if request.method == "POST":
        cliente_id = (request.form.get("cliente_id") or "").strip() or registro.get("cliente_id")
        produto_id = (request.form.get("produto_id") or "").strip() or registro.get("produto_id")
        valor = _to_float(request.form.get("valor") or registro.get("valor"))
        percentual = _to_float(request.form.get("percentual") or registro.get("percentual"))
        efetivada = (request.form.get("efetivada") in ("on", "true", "1"))

        if supabase:
            try:
                uid = _uid()
                if not uid:
                    flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                    return redirect(url_for("alocacoes.index"))
                
                q = supabase.table("alocacoes").update({
                    "cliente_id": cliente_id,
                    "produto_id": produto_id,
                    "valor": valor,
                    "percentual": percentual,
                    "efetivada": efetivada
                }).eq("id", aloc_id).eq("user_id", uid)
                q.execute()
                flash("Alocação atualizada.", "success")
                return redirect(url_for("alocacoes.index", cliente_id=cliente_id))
            except Exception:
                current_app.logger.exception("Falha ao atualizar alocação no Supabase")
                flash("Falha ao atualizar alocação no Supabase.", "error")
                return redirect(url_for("alocacoes.editar", aloc_id=aloc_id))

        if Alocacao:
            try:
                a = db.session.get(Alocacao, aloc_id)
                if not a:
                    flash("Alocação não encontrado (banco local).", "error")
                    return redirect(url_for("alocacoes.index"))
                if hasattr(a, "cliente_id"):
                    a.cliente_id = cliente_id
                if hasattr(a, "produto_id"):
                    a.produto_id = produto_id
                if hasattr(a, "valor"):
                    a.valor = valor
                if hasattr(a, "percentual"):
                    a.percentual = percentual
                if hasattr(a, "efetivada"):
                    a.efetivada = efetivada
                # Garantir que alocações existentes tenham status padrão
                if hasattr(a, "status") and not getattr(a, "status", None):
                    a.status = "mapeado"
                db.session.commit()
                flash("Alocação atualizada (banco local).", "success")
                return redirect(url_for("alocacoes.index", cliente_id=cliente_id))
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar alocação no banco local")
                flash("Falha ao atualizar alocação no banco local.", "error")
                return redirect(url_for("alocacoes.editar", aloc_id=aloc_id))

        flash("Backend indisponível para atualizar alocação.", "error")
        return redirect(url_for("alocacoes.editar", aloc_id=aloc_id))

    clientes, produtos = _carregar_clientes_produtos()
    return render_template(
        "alocacoes/editar.html",
        alocacao=registro,
        clientes=clientes,
        produtos=produtos
    )


# ---------------- TOGGLE EFETIVADA ----------------
@alocacoes_bp.route("/<string:aloc_id>/efetivar", methods=["POST"])
@login_required
def efetivar(aloc_id: str):
    next_url = request.args.get("next") or request.form.get("next")
    cliente_id_redirect = request.args.get("cliente_id") or request.form.get("cliente_id") or None
    new_val = request.form.get("efetivada") in ("on", "true", "1", "True")

    if supabase:
        try:
            uid = _uid()
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for("alocacoes.index"))
            
            q = supabase.table("alocacoes").update({"efetivada": new_val}).eq("id", aloc_id).eq("user_id", uid)
            q.execute()
            flash("Alocação atualizada.", "success")
        except Exception:
            current_app.logger.exception("Falha ao atualizar flag efetivada no Supabase")
            flash("Falha ao atualizar alocação.", "error")
    elif Alocacao:
        try:
            a = db.session.get(Alocacao, aloc_id)
            if a and hasattr(a, "efetivada"):
                a.efetivada = new_val
                db.session.commit()
                flash("Alocação atualizada (banco local).", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Falha ao atualizar flag efetivada no banco local")
            flash("Falha ao atualizar alocação.", "error")

    if next_url:
        return redirect(next_url)
    return redirect(url_for("alocacoes.index", cliente_id=cliente_id_redirect))


# ---------------- ATUALIZAR STATUS ----------------
@alocacoes_bp.route("/<string:aloc_id>/status", methods=["POST"])
@login_required
def atualizar_status(aloc_id: str):
    new_status = request.form.get("status", "mapeado")
    next_url = request.args.get("next") or request.form.get("next") or url_for("alocacoes.index")
    
    if new_status not in ["mapeado", "apresentado", "push_enviado", "confirmado"]:
        flash("Status inválido.", "error")
        return redirect(next_url)
    
    if supabase:
        try:
            uid = _uid()
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(next_url)
            
            q = supabase.table("alocacoes").update({"status": new_status}).eq("id", aloc_id).eq("user_id", uid)
            q.execute()
            flash("Status atualizado.", "success")
        except Exception:
            current_app.logger.exception("Falha ao atualizar status no Supabase")
            flash("Falha ao atualizar status.", "error")
    elif Alocacao:
        try:
            a = db.session.get(Alocacao, aloc_id)
            if a and hasattr(a, "status"):
                a.status = new_status
                db.session.commit()
                flash("Status atualizado (banco local).", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Falha ao atualizar status no banco local")
            flash("Falha ao atualizar status.", "error")
    
    return redirect(next_url)


# ---------------- EXCLUIR ALOCAÇÃO ----------------
@alocacoes_bp.route("/<string:aloc_id>/excluir", methods=["POST"])
@login_required
def excluir(aloc_id: str):
    registro = _get_alocacao_by_id(aloc_id)
    cliente_id_redirect = (registro or {}).get("cliente_id")

    if supabase:
        try:
            uid = _uid()
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for("alocacoes.index"))
            
            q = supabase.table("alocacoes").delete().eq("id", aloc_id).eq("user_id", uid)
            q.execute()
            flash("Alocação excluída.", "success")
            return redirect(url_for("alocacoes.index", cliente_id=cliente_id_redirect))
        except Exception:
            current_app.logger.exception("Falha ao excluir alocação no Supabase")
            flash("Falha ao excluir alocação no Supabase.", "error")
            return redirect(url_for("alocacoes.index", cliente_id=cliente_id_redirect))

    if Alocacao:
        try:
            a = db.session.get(Alocacao, aloc_id)
            if not a:
                flash("Alocação não encontrada (banco local).", "error")
                return redirect(url_for("alocacoes.index"))
            db.session.delete(a)
            db.session.commit()
            flash("Alocação excluída (banco local).", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Falha ao excluir alocação no banco local")
            flash("Falha ao excluir alocação no banco local.", "error")
    return redirect(url_for("alocacoes.index", cliente_id=cliente_id_redirect))


# ---------------- PRODUTOS ----------------
@alocacoes_bp.route("/produtos")
@login_required
def produtos():
    itens = []
    if supabase:
        try:
            uid = _uid()
            q = supabase.table("produtos").select(
                "id, created_at, nome, classe, roa_pct, em_campanha, campanha_mes"
            ).order("nome")
            if uid:
                q = q.eq("user_id", uid)
            res = q.execute()
            itens = res.data or []
        except Exception:
            current_app.logger.exception("Falha ao listar produtos do Supabase")
            itens = []
    elif Produto:
        try:
            itens = db.session.query(Produto).order_by(Produto.nome).all()
        except Exception:
            itens = []

    return render_template("alocacoes/produtos.html", produtos=itens)


@alocacoes_bp.route("/produtos/novo", methods=["GET", "POST"])
@login_required
def produto_novo():
    CLASSES_ATIVO = [
        "Renda Fixa",
        "Fundos",
        "Previdência",
        "Renda Variável (mesa)",
        "Produto Estruturado",
        "COE",
        "Fundo Imobiliário",
        "Offshore",
        "Seguro de Vida",
        "Consórcio",
        "Renda Fixa Digital",
    ]
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        classe = (request.form.get("classe") or "").strip()
        try:
            roa = float(request.form.get("roa_pct") or 0)
        except ValueError:
            roa = 0.0
        em_campanha = request.form.get("em_campanha") == "on"
        campanha_mes = request.form.get("campanha_mes") or None

        if supabase:
            try:
                uid = _uid()
                if not uid:
                    flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                    return redirect(url_for("alocacoes.produto_novo"))

                supabase.table("produtos").insert({
                    "nome": nome,
                    "classe": classe,
                    "roa_pct": roa,
                    "em_campanha": em_campanha,
                    "campanha_mes": campanha_mes,
                    "user_id": uid,  # 👈 agora o produto tem dono
                }).execute()
                flash("Produto cadastrado.", "success")
                return redirect(url_for("alocacoes.produtos"))
            except Exception:
                current_app.logger.exception("Falha ao inserir produto no Supabase")
                flash("Falha ao cadastrar produto no Supabase.", "error")

        if Produto:
            try:
                p = Produto(nome=nome, classe=classe, roa_pct=roa,
                            em_campanha=em_campanha, campanha_mes=campanha_mes)
                db.session.add(p)
                db.session.commit()
                flash("Produto cadastrado (banco local).", "success")
                return redirect(url_for("alocacoes.produtos"))
            except Exception:
                current_app.logger.exception("Falha ao inserir produto no banco local")
                flash("Falha ao cadastrar produto no banco local.", "error")

    return render_template("alocacoes/produto_novo.html",
                           classes=CLASSES_ATIVO)
                           
@alocacoes_bp.route("/produtos/<string:id>/editar", methods=["GET", "POST"])
@login_required
def produto_editar(id: str):
    # carregar produto do dono
    produto = None
    if supabase:
        try:
            uid = _uid()
            q = supabase.table("produtos").select(
                "id, nome, classe, roa_pct, em_campanha, campanha_mes"
            ).eq("id", id).limit(1)
            if uid:
                q = q.eq("user_id", uid)
            res = q.execute()
            data = res.data or []
            produto = data[0] if data else None
        except Exception:
            current_app.logger.exception("Falha ao carregar produto no Supabase")
            produto = None
    elif Produto:
        try:
            p = db.session.get(Produto, id)
            if p:
                produto = {
                    "id": getattr(p, "id", id),
                    "nome": getattr(p, "nome", ""),
                    "classe": getattr(p, "classe", None),
                    "roa_pct": getattr(p, "roa_pct", None),
                    "em_campanha": getattr(p, "em_campanha", False),
                    "campanha_mes": getattr(p, "campanha_mes", None),
                }
        except Exception:
            current_app.logger.exception("Falha ao carregar produto no banco local")

    if not produto:
        flash("Produto não encontrado.", "error")
        return redirect(url_for("alocacoes.produtos"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        classe = (request.form.get("classe") or "").strip()
        try:
            roa = float(request.form.get("roa_pct") or 0)
        except ValueError:
            roa = 0.0
        em_campanha = request.form.get("em_campanha") == "on"
        campanha_mes = request.form.get("campanha_mes") or None

        if supabase:
            try:
                uid = _uid()
                q = supabase.table("produtos").update({
                    "nome": nome,
                    "classe": classe,
                    "roa_pct": roa,
                    "em_campanha": em_campanha,
                    "campanha_mes": campanha_mes,
                }).eq("id", id)
                if uid:
                    q = q.eq("user_id", uid)
                q.execute()
                flash("Produto atualizado.", "success")
                return redirect(url_for("alocacoes.produtos"))
            except Exception:
                current_app.logger.exception("Falha ao atualizar produto no Supabase")
                flash("Falha ao atualizar produto no Supabase.", "error")
                return redirect(url_for("alocacoes.produto_editar", id=id))

        if Produto:
            try:
                p = db.session.get(Produto, id)
                if not p:
                    flash("Produto não encontrado (banco local).", "error")
                    return redirect(url_for("alocacoes.produtos"))
                if hasattr(p, "nome"):
                    p.nome = nome
                if hasattr(p, "classe"):
                    p.classe = classe
                if hasattr(p, "roa_pct"):
                    p.roa_pct = roa
                if hasattr(p, "em_campanha"):
                    p.em_campanha = em_campanha
                if hasattr(p, "campanha_mes"):
                    p.campanha_mes = campanha_mes
                db.session.commit()
                flash("Produto atualizado (banco local).", "success")
                return redirect(url_for("alocacoes.produtos"))
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Falha ao atualizar produto no banco local")
                flash("Falha ao atualizar produto no banco local.", "error")
                return redirect(url_for("alocacoes.produto_editar", id=id))

        flash("Backend indisponível para atualizar produto.", "error")
        return redirect(url_for("alocacoes.produto_editar", id=id))

    # GET -> renderiza formulário
    CLASSES_ATIVO = [
        "Renda Fixa", "Fundos", "Previdência", "Renda Variável (mesa)",
        "Produto Estruturado", "COE", "Fundo Imobiliário", "Offshore",
        "Seguro de Vida", "Consórcio", "Renda Fixa Digital",
    ]
    return render_template("alocacoes/produto_editar.html",
                           p=produto, classes=CLASSES_ATIVO)



# ---- Exclusões de produto (individual e em massa) ----
@alocacoes_bp.route("/produtos/<string:id>/excluir", methods=["POST"])
@login_required
def produto_excluir(id: str):
    if supabase:
        try:
            uid = _uid()
            q = supabase.table("produtos").delete().eq("id", id)
            if uid:
                q = q.eq("user_id", uid)
            q.execute()
            flash("Produto excluído.", "success")
            return redirect(url_for("alocacoes.produtos"))
        except Exception:
            current_app.logger.exception("Falha ao excluir produto no Supabase")
            flash("Falha ao excluir produto no Supabase.", "error")
            return redirect(url_for("alocacoes.produtos"))
    if Produto:
        try:
            if Alocacao:
                db.session.query(Alocacao).filter_by(produto_id=id).delete()
            db.session.query(Produto).filter_by(id=id).delete()
            db.session.commit()
            flash("Produto excluído (banco local).", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Falha ao excluir produto no banco local")
            flash("Falha ao excluir produto no banco local.", "error")
    return redirect(url_for("alocacoes.produtos"))


@alocacoes_bp.route("/produtos/excluir-todos", methods=["POST"])
@login_required
def produto_excluir_todos():
    if supabase:
        try:
            uid = _uid()
            q = supabase.table("produtos").delete()
            if uid:
                q = q.eq("user_id", uid)
            else:
                q = q.neq("id", "")  # fallback (evite em prod)
            q.execute()
            flash("Todos os produtos foram excluídos.", "success")
            return redirect(url_for("alocacoes.produtos"))
        except Exception:
            current_app.logger.exception("Falha ao excluir todos os produtos no Supabase")
            flash("Falha ao excluir todos os produtos no Supabase.", "error")
            return redirect(url_for("alocacoes.produtos"))
    if Produto:
        try:
            if Alocacao:
                db.session.query(Alocacao).delete()
            db.session.query(Produto).delete()
            db.session.commit()
            flash("Todos os produtos foram excluídos (banco local).", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Falha ao excluir todos os produtos no banco local")
            flash("Falha ao excluir todos os produtos no banco local.", "error")
    return redirect(url_for("alocacoes.produtos"))
