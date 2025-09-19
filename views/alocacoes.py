from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from utils import login_required
from models import db  # fallback local opcional
from cache_manager import cached_by_user, invalidate_user_cache

def _invalidar_cache_relacionado():
    """Invalida caches relacionados quando dados de alocação mudam."""
    try:
        # Invalidar cache do dashboard quando alocações mudam
        from views.dashboard import invalidar_cache_dashboard
        invalidar_cache_dashboard()

        # Invalidar caches locais (incluindo o novo cache de alocações)
        invalidate_user_cache('alocacoes_receitas')
        invalidate_user_cache('dashboard_data')
        invalidate_user_cache('receitas_calc')
        invalidate_user_cache('clientes_list')
        invalidate_user_cache('produtos_list')

        # Força limpeza completa do cache do usuário para garantir
        from cache_manager import invalidate_all_user_cache
        invalidate_all_user_cache()

        current_app.logger.info("Cache relacionado invalidado com sucesso")
    except Exception as e:
        from flask import current_app
        current_app.logger.error("Erro ao invalidar cache relacionado: %s", e)
# (Opcional) se você tiver modelos locais para Produto/Alocacao/Cliente, pode importar
try:
    from models import Cliente, Produto, Alocacao
except Exception:
    Cliente = Produto = Alocacao = None

# Supabase opcional (não quebra se não estiver configurado)
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
        current_app.logger.debug("ALOCACOES: Cliente Supabase não disponível (usuário não autenticado)")
    return client

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
    # Usar a mesma lógica do security_middleware
    from security_middleware import get_current_user_id
    return get_current_user_id()

def _calcular_receitas_dashboard(cliente_id_filter=None):
    """
    Calcula receitas e totais com cache para melhorar performance.

    Args:
        cliente_id_filter: ID do cliente para filtrar (opcional)

    Returns:
        dict: Dados calculados incluindo totais e receitas
    """
    uid = _uid()
    supabase = _get_supabase()

    result = {
        'alocacoes': [],
        'totais_por_status': {
            "mapeado": 0.0,
            "apresentado": 0.0,
            "push_enviado": 0.0,
            "confirmado": 0.0
        },
        'receitas_por_status': {
            "mapeado": 0.0,
            "apresentado": 0.0,
            "push_enviado": 0.0,
            "confirmado": 0.0
        },
        'total_geral': 0.0,
        'total_rec_escritorio': 0.0,
        'total_rec_assessor': 0.0,
        'by_cliente': {},
        'by_cliente_tradicional': {},
        'by_cliente_fee_based': {},
        'by_produto_receita': {}
    }

    if not supabase:
        return result

    try:
        q = supabase.table("alocacoes").select(
            "id, percentual, valor, cliente_id, produto_id, efetivada, "
            "cliente:cliente_id ( id, nome, modelo, repasse ), "
            "produto:produto_id ( id, nome, classe, roa_pct, em_campanha, campanha_mes )"
        ).order("created_at", desc=False)

        if uid:
            q = q.eq("user_id", uid)
        if cliente_id_filter:
            q = q.eq("cliente_id", cliente_id_filter)

        res = q.execute()

        for r in res.data or []:
            valor = _to_float(r.get("valor"))
            cliente = r.get("cliente") or {}
            produto = r.get("produto") or {}

            modelo = cliente.get("modelo") or ""
            repasse = cliente.get("repasse") or 35
            classe = produto.get("classe") or ""
            roa_pct = _to_float(produto.get("roa_pct"))

            # Definir status baseado em efetivada e percentual
            efetivada = r.get("efetivada", False)
            percentual = _to_float(r.get("percentual", 0))

            if efetivada:
                status = "confirmado"
            elif percentual >= 75:
                status = "push_enviado"
            elif percentual >= 50:
                status = "apresentado"
            else:
                status = "mapeado"

            # Calcular receitas
            rec_escr, rec_ass, rec_base = _calc_receitas(valor, roa_pct, repasse, modelo, classe)

            # Somar no total geral sempre
            result['total_geral'] += valor
            result['totais_por_status'][status] += valor
            result['receitas_por_status'][status] += rec_escr

            # Receitas só para confirmados (receita efetiva)
            if status == "confirmado":
                result['total_rec_escritorio'] += rec_escr
                result['total_rec_assessor'] += rec_ass

                # Para o gráfico donut
                pid, pnome = produto.get("id"), produto.get("nome") or ""
                if pid:
                    acc = result['by_produto_receita'].setdefault(pid, {"nome": pnome, "receita": 0.0})
                    acc["receita"] += rec_escr

            # By cliente (todos os status)
            cid, cnome = cliente.get("id"), cliente.get("nome") or ""
            cmodelo = (cliente.get("modelo") or "").strip().upper()
            if cid:
                acc = result['by_cliente'].setdefault(cid, {"nome": cnome, "valor": 0.0})
                acc["valor"] += valor

                # Segmentar por modelo
                if cmodelo == "TRADICIONAL":
                    acc_trad = result['by_cliente_tradicional'].setdefault(cid, {"nome": cnome, "valor": 0.0})
                    acc_trad["valor"] += valor
                elif cmodelo in ["FEE_BASED", "FEE_BASED_SEM_RV"]:
                    acc_fee = result['by_cliente_fee_based'].setdefault(cid, {"nome": cnome, "valor": 0.0})
                    acc_fee["valor"] += valor

            # Adicionar item processado
            item = dict(r)
            item.update({
                "receita_base": rec_base,
                "receita_escritorio": rec_escr,
                "receita_assessor": rec_ass,
                "receita_escritorio_efetiva": rec_escr if status == "confirmado" else 0.0,
                "receita_assessor_efetiva": rec_ass if status == "confirmado" else 0.0,
                "repasse": repasse,
                "status": status
            })
            result['alocacoes'].append(item)

    except Exception:
        current_app.logger.exception("Falha ao calcular receitas no Supabase")

    return result


def _carregar_clientes():
    """Carrega lista de clientes do usuário com cache."""
    clientes = []
    uid = _uid()
    supabase = _get_supabase()
    if supabase:
        try:
            cres = supabase.table("clientes").select("id, nome").order("nome")
            if uid:
                cres = cres.eq("user_id", uid)
            else:
                return []
            clientes = (cres.execute().data or [])
        except Exception:
            current_app.logger.exception("Falha ao carregar clientes do Supabase")
            clientes = []
    return clientes

def _carregar_produtos():
    """Carrega lista de produtos do usuário com cache."""
    produtos = []
    uid = _uid()
    supabase = _get_supabase()
    if supabase:
        try:
            pres = supabase.table("produtos").select("id, nome, classe").order("nome")
            if uid:
                pres = pres.eq("user_id", uid)
            else:
                return []
            produtos = (pres.execute().data or [])
        except Exception:
            current_app.logger.exception("Falha ao carregar produtos do Supabase")
            produtos = []
    return produtos

def _carregar_clientes_produtos():
    """Wrapper que usa as funções com cache individual."""
    clientes = _carregar_clientes()
    produtos = _carregar_produtos()
    return clientes, produtos

def _carregar_clientes_produtos_original():
    """Função original sem cache - mantida como backup."""
    clientes, produtos = [], []
    uid = _uid()
    supabase = _get_supabase()
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
    return clientes, produtos


def _get_alocacao_by_id(aloc_id: str):
    supabase = _get_supabase()
    if supabase:
        try:
            uid = _uid()
            q = supabase.table("alocacoes").select(
                "id, cliente_id, produto_id, valor, percentual, efetivada, "
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
                    "status": "mapeado",  # Padrão até coluna ser criada
                    "cliente": r.get("cliente") or {},
                    "produto": r.get("produto") or {},
                }
        except Exception:
            current_app.logger.exception("Falha ao carregar alocação no Supabase")
            return None

    return None


# ---------------- LISTAGEM ----------------
@alocacoes_bp.route("/")
@login_required
def index():
    cliente_id_filter = (request.args.get("cliente_id") or "").strip() or None

    # Usar função com cache para buscar e calcular receitas
    cached_data = _calcular_receitas_dashboard(cliente_id_filter)

    # Extrair dados do cache
    enriched = cached_data['alocacoes']
    totais_por_status = cached_data['totais_por_status']
    receitas_por_status = cached_data['receitas_por_status']
    total_geral = cached_data['total_geral']
    total_rec_escritorio = cached_data['total_rec_escritorio']
    total_rec_assessor = cached_data['total_rec_assessor']
    by_cliente = cached_data['by_cliente']
    by_cliente_tradicional = cached_data['by_cliente_tradicional']
    by_cliente_fee_based = cached_data['by_cliente_fee_based']
    by_produto_receita = cached_data['by_produto_receita']

    totais_clientes = sorted(by_cliente.values(), key=lambda x: x["valor"], reverse=True)
    totais_clientes_tradicional = sorted(by_cliente_tradicional.values(), key=lambda x: x["valor"], reverse=True)
    totais_clientes_fee_based = sorted(by_cliente_fee_based.values(), key=lambda x: x["valor"], reverse=True)
    receitas_por_produto = sorted(by_produto_receita.values(), key=lambda x: x["receita"], reverse=True)

    # Organizar alocações por status para o kanban
    kanban = {
        "mapeado": [],
        "apresentado": [],
        "push_enviado": [],
        "confirmado": []
    }
    
    for a in enriched:
        status = a.get("status", "mapeado")
        kanban[status].append(a)

    # Ordenar cada coluna do kanban alfabeticamente por nome do cliente
    for status in kanban:
        kanban[status].sort(key=lambda x: (x.get("cliente", {}).get("nome") or "").upper())

    # Buscar produtos para o simulador de meta
    produtos_data = []
    supabase_produtos = _get_supabase()
    if supabase_produtos:
        try:
            uid = _uid()
            if uid:
                q = supabase_produtos.table("produtos").select("id, nome, classe, roa_pct, em_campanha, campanha_mes").eq("user_id", uid)
                resp = q.execute()
                produtos_data = resp.data or []
        except Exception:
            pass
    
    # BÔNUS/MISSÕES - Carregar bônus do mês atual
    bonus_list = _carregar_bonus_mes()
    total_bonus = sum(
        _calcular_valor_liquido_bonus(
            b.get("valor_bonus", 0),
            b.get("liquido_assessor", True)
        )
        for b in bonus_list if b.get("ativo", True)
    )

    # SIMULADOR DE META - Calcular alocações necessárias para atingir meta (incluindo bônus)
    receita_atual_com_bonus = total_rec_escritorio + total_bonus
    simulador_meta = _calcular_simulador_meta(_uid(), receita_atual_com_bonus, produtos_data, enriched)

    return render_template(
        "alocacoes/index.html",
        alocacoes=enriched,
        kanban=kanban,
        total_geral=total_geral,
        totais_por_status=totais_por_status,
        receitas_por_status=receitas_por_status,
        totais_clientes=totais_clientes,
        totais_clientes_tradicional=totais_clientes_tradicional,
        totais_clientes_fee_based=totais_clientes_fee_based,
        receitas_por_produto=receitas_por_produto,
        total_rec_escritorio=total_rec_escritorio,
        total_rec_assessor=total_rec_assessor,
        cliente_id_filter=cliente_id_filter,
        simulador_meta=simulador_meta,
        bonus_list=bonus_list,
        total_bonus=total_bonus,
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

        supabase = _get_supabase()
        if not supabase:
            flash("Sistema indisponível. Tente novamente mais tarde.", "error")
            return redirect(url_for("alocacoes.novo"))

        try:
            uid = _uid()
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for("alocacoes.novo"))

            # Verificar se já existe uma alocação para esta combinação cliente + produto
            existing_check = supabase.table("alocacoes").select("id, valor").eq("cliente_id", cliente_id).eq("produto_id", produto_id).eq("user_id", uid).execute()

            if existing_check.data:
                # Já existe: atualizar somando o valor
                existing_alocacao = existing_check.data[0]
                existing_id = existing_alocacao["id"]
                existing_valor = _to_float(existing_alocacao.get("valor", 0))
                novo_valor = existing_valor + valor

                supabase.table("alocacoes").update({
                    "valor": novo_valor
                }).eq("id", existing_id).eq("user_id", uid).execute()

                flash(f"Valor adicionado à alocação existente! Novo total: R$ {novo_valor:,.2f}", "success")
            else:
                # Não existe: inserir nova alocação
                supabase.table("alocacoes").insert({
                    "cliente_id": cliente_id,
                    "produto_id": produto_id,
                    "valor": valor,
                    "percentual": 0,
                    "efetivada": False,
                    "user_id": uid,
                }).execute()

                flash("Alocação cadastrada com sucesso!", "success")

            # Invalidar todos os caches relacionados APÓS qualquer mudança
            _invalidar_cache_relacionado()

            # Adicionar timestamp para forçar refresh completo
            import time
            return redirect(url_for("alocacoes.index", _t=int(time.time())))
        except Exception as e:
            current_app.logger.exception("Falha ao inserir alocação no Supabase")
            flash(f"Erro ao cadastrar alocação: {str(e)}", "error")
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
        # Manter valores existentes de percentual e efetivada (campos removidos do form)
        percentual = registro.get("percentual", 0)
        efetivada = registro.get("efetivada", False)

        supabase = _get_supabase()
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

                # Invalidar cache após atualização
                _invalidar_cache_relacionado()

                flash("Alocação atualizada.", "success")
                # Forçar refresh após edição
                import time
                return redirect(url_for("alocacoes.index", _t=int(time.time())))
            except Exception:
                current_app.logger.exception("Falha ao atualizar alocação no Supabase")
                flash("Falha ao atualizar alocação no Supabase.", "error")
                return redirect(url_for("alocacoes.editar", aloc_id=aloc_id))
        else:
            flash("Sistema indisponível. Tente novamente mais tarde.", "error")
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

    supabase = _get_supabase()
    if supabase:
        try:
            uid = _uid()
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for("alocacoes.index"))
            
            q = supabase.table("alocacoes").update({"efetivada": new_val}).eq("id", aloc_id).eq("user_id", uid)
            q.execute()

            # Invalidar todos os caches relacionados
            _invalidar_cache_relacionado()

            flash("Alocação atualizada.", "success")
        except Exception:
            current_app.logger.exception("Falha ao atualizar flag efetivada no Supabase")
            flash("Falha ao atualizar alocação.", "error")
    else:
        flash("Sistema indisponível. Tente novamente mais tarde.", "error")

    if next_url:
        return redirect(next_url)
    return redirect(url_for("alocacoes.index"))


# ---------------- ATUALIZAR STATUS ----------------
@alocacoes_bp.route("/<string:aloc_id>/status", methods=["POST"])
@login_required
def atualizar_status(aloc_id: str):
    from flask import jsonify
    supabase = _get_supabase()
    new_status = request.form.get("status", "mapeado")
    next_url = request.args.get("next") or request.form.get("next") or url_for("alocacoes.index")

    # Verificar se é uma requisição AJAX
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')

    if new_status not in ["mapeado", "apresentado", "push_enviado", "confirmado"]:
        if is_ajax:
            return jsonify({"success": False, "message": "Status inválido"}), 400
        flash("Status inválido.", "error")
        return redirect(next_url)

    if supabase:
        try:
            uid = _uid()
            if not uid:
                if is_ajax:
                    return jsonify({"success": False, "message": "Sessão inválida"}), 401
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(next_url)
            
            # Verificar se a alocação existe e pertence ao usuário antes de atualizar
            check_q = supabase.table("alocacoes").select("id,user_id").eq("id", aloc_id).eq("user_id", uid)
            check_result = check_q.execute()

            if not check_result.data:
                if is_ajax:
                    return jsonify({"success": False, "message": "Alocação não encontrada ou você não tem permissão para modificá-la"}), 404
                flash("Alocação não encontrada ou você não tem permissão para modificá-la.", "error")
                return redirect(next_url)

            # Mapear status para campos existentes (simulação)
            updates = {}

            if new_status == "mapeado":
                updates = {"percentual": 0, "efetivada": False}
            elif new_status == "apresentado":
                updates = {"percentual": 50, "efetivada": False}
            elif new_status == "push_enviado":
                updates = {"percentual": 75, "efetivada": False}
            elif new_status == "confirmado":
                updates = {"percentual": 100, "efetivada": True}

            q = supabase.table("alocacoes").update(updates).eq("id", aloc_id).eq("user_id", uid)
            result = q.execute()

            # Verificar se a atualização foi bem-sucedida
            if not result.data:
                if is_ajax:
                    return jsonify({"success": False, "message": "Falha ao atualizar: alocação pode ter sido modificada por outro usuário"}), 409
                flash("Falha ao atualizar: alocação pode ter sido modificada por outro usuário.", "error")
                return redirect(next_url)

            # Invalidar cache após mudança de status
            _invalidar_cache_relacionado()

            message = ""
            if new_status == "confirmado":
                message = "Alocação movida para Confirmado e marcada como efetivada!"
            else:
                message = f"Alocação movida para {new_status.replace('_', ' ').title()}."

            if is_ajax:
                return jsonify({"success": True, "message": message})
            else:
                flash(message, "success")
                
        except Exception as e:
            current_app.logger.exception("Falha ao atualizar status no Supabase")
            if is_ajax:
                return jsonify({"success": False, "message": "Falha ao atualizar status"}), 500
            flash("Falha ao atualizar status.", "error")
    else:
        message = "Sistema indisponível. Tente novamente mais tarde."
        if is_ajax:
            return jsonify({"success": False, "message": message}), 503
        flash(message, "error")
    
    if is_ajax:
        return jsonify({"success": False, "message": "Erro desconhecido"}), 500
    return redirect(next_url)


# ---------------- EXCLUIR ALOCAÇÃO ----------------
@alocacoes_bp.route("/<string:aloc_id>/excluir", methods=["POST"])
@login_required
def excluir(aloc_id: str):
    supabase = _get_supabase()
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

            # Invalidar cache após exclusão
            _invalidar_cache_relacionado()

            flash("Alocação excluída.", "success")
            # Forçar refresh completo após exclusão
            import time
            return redirect(url_for("alocacoes.index", _t=int(time.time())))
        except Exception:
            current_app.logger.exception("Falha ao excluir alocação no Supabase")
            flash("Falha ao excluir alocação no Supabase.", "error")
            return redirect(url_for("alocacoes.index"))
    else:
        flash("Sistema indisponível. Tente novamente mais tarde.", "error")
        
    return redirect(url_for("alocacoes.index"))


# ---------------- PRODUTOS ----------------
@alocacoes_bp.route("/produtos")
@login_required
def produtos():
    supabase = _get_supabase()
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
        "Câmbio",
        "COE",
        "Corporate",
        "Fundo Imobiliário",
        "Fundos",
        "Offshore",
        "Previdência",
        "Produto Estruturado",
        "Renda Fixa",
        "Renda Fixa Digital",
        "Renda Variável (mesa)",
        "Seguro de Vida",
        "Wealth Management (WM)",
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

        supabase = _get_supabase()
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

                # Invalidar cache de produtos
                invalidate_user_cache('produtos_list')

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
    supabase = _get_supabase()
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

        supabase = _get_supabase()
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
        "Câmbio", "COE", "Corporate", "Fundo Imobiliário", "Fundos",
        "Offshore", "Previdência", "Produto Estruturado", "Renda Fixa",
        "Renda Fixa Digital", "Renda Variável (mesa)", "Seguro de Vida",
        "Wealth Management (WM)",
    ]
    return render_template("alocacoes/produto_editar.html",
                           p=produto, classes=CLASSES_ATIVO)



# ---- Exclusões de produto (individual e em massa) ----
@alocacoes_bp.route("/produtos/<string:id>/excluir", methods=["POST"])
@login_required
def produto_excluir(id: str):
    supabase = _get_supabase()
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
    supabase = _get_supabase()
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


@alocacoes_bp.route("/receitas-ajax", methods=["GET"])
@login_required
def receitas_ajax():
    """Endpoint AJAX para retornar receitas atualizadas em tempo real"""
    from flask import jsonify
    
    try:
        uid = _uid()
        alocacoes_data = []
        
        supabase = _get_supabase()
        if supabase:
            q = supabase.table("alocacoes").select("*, clientes:cliente_id(*), produtos:produto_id(*)").order("id")
            if uid:
                q = q.eq("user_id", uid)
            resp = q.execute()
            alocacoes_data = resp.data
        
        # Calcular receitas apenas para alocações confirmadas
        total_rec_escritorio = 0.0
        total_rec_assessor = 0.0
        receitas_por_produto = {}
        
        for a in alocacoes_data:
            if not _is_confirmed(a.get("percentual"), a.get("efetivada")):
                continue
                
            valor = _to_float(a.get("valor"))
            if valor <= 0:
                continue
                
            produto = a.get("produtos", {})
            cliente = a.get("clientes", {})
            
            if not produto or not cliente:
                continue
                
            roa_pct = _to_float(produto.get("roa_pct"))
            classe = produto.get("classe", "")
            repasse = _to_float(cliente.get("repasse"))
            modelo = cliente.get("modelo", "")

            if roa_pct <= 0:
                continue

            # Calcular receitas
            rec_escritorio, rec_assessor, _ = _calc_receitas(valor, roa_pct, repasse, modelo, classe)
            total_rec_escritorio += rec_escritorio
            total_rec_assessor += rec_assessor
            
            # Agrupar por produto para o gráfico
            produto_nome = produto.get("nome", "Produto desconhecido")
            if produto_nome not in receitas_por_produto:
                receitas_por_produto[produto_nome] = 0.0
            receitas_por_produto[produto_nome] += rec_escritorio + rec_assessor
        
        # Preparar dados para o gráfico (top 10)
        receitas_produtos_list = [
            {"nome": nome, "receita": receita}
            for nome, receita in sorted(receitas_por_produto.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        
        return jsonify({
            "receita_escritorio": total_rec_escritorio,
            "receita_assessor": total_rec_assessor,
            "receitas_por_produto": receitas_produtos_list
        })
        
    except Exception as e:
        current_app.logger.exception("Erro ao buscar receitas AJAX")
        return jsonify({"error": "Erro interno"}), 500


def _is_confirmed(percentual, efetivada):
    """Verifica se a alocação está confirmada baseada na lógica de status"""
    if efetivada:
        return True
    # Considerar também alocações com percentual como "aplicadas"
    # para fins de cálculo do valor restante (todas as colunas exceto "mapeado")
    percentual_float = _to_float(percentual)
    if percentual_float >= 50:  # apresentado, push_enviado ou superior
        return True
    return False


def _calcular_simulador_meta(uid, receita_atual, produtos_data, alocacoes_data=None):
    """Calcula quanto precisa alocar em cada produto para atingir as metas por classe"""
    from datetime import datetime

    supabase = _get_supabase()
    mes_atual = datetime.now().strftime("%Y-%m")

    # Carregar bônus ativos para exibição separada
    bonus_ativo_mes = 0.0
    try:
        if supabase and uid:
            # Tentar com colunas novas primeiro
            try:
                resp_bonus = supabase.table("bonus_missoes").select("valor_bonus, liquido_assessor").eq("user_id", uid).eq("mes", mes_atual).eq("ativo", True).execute()
                bonus_list = resp_bonus.data or []
                bonus_ativo_mes = sum(
                    _calcular_valor_liquido_bonus(
                        b.get("valor_bonus", 0),
                        b.get("liquido_assessor", True)
                    )
                    for b in bonus_list
                )
            except Exception:
                # Fallback para apenas valor_bonus
                resp_bonus = supabase.table("bonus_missoes").select("valor_bonus").eq("user_id", uid).eq("mes", mes_atual).eq("ativo", True).execute()
                bonus_list = resp_bonus.data or []
                bonus_ativo_mes = sum(_to_float(b.get("valor_bonus", 0)) for b in bonus_list)
                current_app.logger.warning("SIMULADOR_META: Usando fallback (campos novos não disponíveis)")
    except Exception as e:
        current_app.logger.warning("SIMULADOR_META: Erro ao carregar bônus: %s", e)
        bonus_ativo_mes = 0.0
    
    # Buscar metas por classe do mês atual
    metas_por_classe = {}
    total_metas = 0.0

    try:
        if supabase and uid:
            resp = supabase.table("metas_escritorio_classe").select("*").eq("user_id", uid).eq("mes", mes_atual).execute()
            current_app.logger.info(f"DEBUG METAS: Encontradas {len(resp.data or [])} metas para {mes_atual}")
            for meta in resp.data or []:
                classe = meta.get("classe", "")
                meta_receita = _to_float(meta.get("meta_receita", 0))
                current_app.logger.info(f"Meta encontrada: {classe} = R${meta_receita:,.2f}")
                if meta_receita > 0:  # Só considerar metas > 0
                    metas_por_classe[classe] = meta_receita
                    total_metas += meta_receita
            current_app.logger.info(f"Total de metas válidas: R${total_metas:,.2f}")
    except Exception as e:
        current_app.logger.exception("Erro ao buscar metas por classe")
    
    # Se não há metas definidas, retornar vazio
    if not metas_por_classe:
        return {
            "meta_mes": 0.0,
            "receita_atual": receita_atual,
            "receita_passiva": 0.0,
            "bonus_ativo": bonus_ativo_mes,
            "receita_total_esperada": receita_atual,
            "falta_receita": 0.0,
            "produtos_sugestao": [],
            "mes_atual": mes_atual,
            "metas_por_classe": {}
        }
    
    # Calcular receita passiva usando a MESMA lógica do dashboard
    try:
        clientes_data = []
        if supabase and uid:
            clientes_resp = supabase.table("clientes").select("*").eq("user_id", uid).execute()
            clientes_data = clientes_resp.data or []
        
        from views.dashboard import _receita_escritorio_recorrente
        receita_passiva_mes = _receita_escritorio_recorrente(clientes_data)
        
    except Exception as e:
        current_app.logger.warning(f"Erro ao calcular receita passiva via dashboard: {e}")
        receita_passiva_mes = 0.0
    
    # Calcular valor financeiro já aplicado por produto (APENAS confirmados)
    # Usar os dados já processados em vez de fazer nova consulta
    valor_aplicado_por_produto = {}

    if alocacoes_data:
        current_app.logger.info("=== DEBUG SIMULADOR (usando dados processados) ===")
        current_app.logger.info(f"Total alocações recebidas: {len(alocacoes_data)}")

        for i, alocacao in enumerate(alocacoes_data):
            valor = _to_float(alocacao.get("valor", 0))
            produto = alocacao.get("produto") or {}
            produto_id = produto.get("id", "").strip()
            produto_nome = produto.get("nome", "").strip()
            status = alocacao.get("status", "mapeado")

            current_app.logger.info(f"Alocação {i+1}: {produto_nome} (ID:{produto_id}) = R${valor:,.2f}, Status: {status}")

            # Incluir APENAS aplicações confirmadas
            if status == "confirmado" and valor > 0 and produto_id:
                if produto_id not in valor_aplicado_por_produto:
                    valor_aplicado_por_produto[produto_id] = 0.0
                valor_aplicado_por_produto[produto_id] += valor
                current_app.logger.info(f"  -> CONFIRMADA: Adicionando R${valor:,.2f} ao produto {produto_id}")

        current_app.logger.info(f"Valores aplicados confirmados: {valor_aplicado_por_produto}")
        current_app.logger.info("=== FIM DEBUG ===")
    else:
        current_app.logger.warning("SIMULADOR - Nenhum dado de alocações recebido")

    # Agrupar produtos por classe
    produtos_por_classe = {}
    for produto in produtos_data:
        classe = produto.get("classe", "").strip()
        if classe not in produtos_por_classe:
            produtos_por_classe[classe] = []
        produtos_por_classe[classe].append(produto)
    
    # Calcular sugestões para cada classe que tem meta definida
    produtos_sugestao = []
    receita_total_esperada = receita_atual + receita_passiva_mes
    falta_receita_total = 0.0
    
    for classe, meta_classe in metas_por_classe.items():
        # Produtos válidos desta classe
        produtos_classe = produtos_por_classe.get(classe, [])
        produtos_validos_classe = []
        total_peso_roa_classe = 0
        
        for produto in produtos_classe:
            roa_pct = _to_float(produto.get("roa_pct", 0))
            if roa_pct > 0:
                produtos_validos_classe.append(produto)
                total_peso_roa_classe += roa_pct
        
        if not produtos_validos_classe:
            current_app.logger.warning(f"Classe '{classe}' tem meta definida mas nenhum produto válido")
            continue
        
        # Meta dividida igualmente entre produtos da classe
        qtd_produtos_classe = len(produtos_validos_classe)
        meta_receita_por_produto = meta_classe / qtd_produtos_classe if qtd_produtos_classe > 0 else 0
        
        current_app.logger.info(f"SIMULADOR - Classe '{classe}': Meta total={meta_classe}, Produtos={qtd_produtos_classe}, Meta por produto={meta_receita_por_produto}")
        
        for produto in produtos_validos_classe:
            roa_pct = _to_float(produto.get("roa_pct", 0))
            produto_nome = produto.get("nome", "")
            produto_id = produto.get("id", "")

            if roa_pct <= 0:
                continue

            # Valor financeiro necessário para gerar a meta de receita deste produto
            # Receita Escritório = Valor Aplicado × ROA%
            # Logo: Valor Necessário = Meta Receita ÷ ROA%
            valor_necessario = meta_receita_por_produto / (roa_pct / 100.0)

            # Valor já aplicado neste produto (APENAS aplicações confirmadas)
            valor_ja_aplicado = valor_aplicado_por_produto.get(produto_id, 0.0)

            # Valor restante = Valor necessário - Valor já aplicado
            valor_restante = max(0, valor_necessario - valor_ja_aplicado)

            # Log detalhado do cálculo
            current_app.logger.info(f"CALC DEBUG - {produto_nome} (ID:{produto_id}): Necessário=R${valor_necessario:,.2f}, Aplicado=R${valor_ja_aplicado:,.2f}, Restante=R${valor_restante:,.2f}")
            
            # Receita que seria gerada se aplicasse o valor necessário
            receita_gerada = valor_necessario * (roa_pct / 100.0)

            produto_info = {
                "id": produto.get("id"),  # Incluir ID do produto para o template
                "nome": produto_nome,
                "classe": classe,
                "roa_pct": roa_pct,
                "meta_classe": meta_classe,
                "meta_receita_por_produto": meta_receita_por_produto,
                "valor_necessario": valor_necessario,
                "valor_ja_aplicado": valor_ja_aplicado,
                "valor_restante": valor_restante,
                "receita_gerada": receita_gerada,
                "em_campanha": produto.get("em_campanha", False)
            }
            
            # Adicionar à lista
            produtos_sugestao.append(produto_info)
    
    # Calcular receita faltante = Meta - Receita Ativa - Receita Passiva
    receita_total_esperada = receita_atual + receita_passiva_mes
    falta_receita = max(0, total_metas - receita_total_esperada)

    # DEBUG: Log do cálculo "Falta Atingir"
    current_app.logger.info(f"=== CÁLCULO FALTA ATINGIR ===")
    current_app.logger.info(f"Total metas: R${total_metas:,.2f}")
    current_app.logger.info(f"Receita atual (param): R${receita_atual:,.2f}")
    current_app.logger.info(f"Receita passiva: R${receita_passiva_mes:,.2f}")
    current_app.logger.info(f"Receita total esperada: R${receita_total_esperada:,.2f}")
    current_app.logger.info(f"Falta atingir: R${falta_receita:,.2f}")
    current_app.logger.info(f"=== FIM CÁLCULO =====")
    
    # Ordenar por classe e ROA
    produtos_sugestao.sort(key=lambda x: (x["classe"], -x["roa_pct"]))
    
    return {
        "meta_mes": total_metas,
        "receita_atual": receita_atual,
        "receita_passiva": receita_passiva_mes,
        "bonus_ativo": bonus_ativo_mes,
        "receita_total_esperada": receita_total_esperada,
        "falta_receita": falta_receita,
        "produtos_sugestao": produtos_sugestao,
        "mes_atual": mes_atual,
        "metas_por_classe": metas_por_classe
    }


# ---------------- BÔNUS/MISSÕES ----------------
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

def _carregar_bonus_mes():
    """Carrega bônus/missões do usuário para o mês atual"""
    from datetime import datetime
    uid = _uid()
    supabase = _get_supabase()
    mes_atual = datetime.now().strftime("%Y-%m")
    bonus_list = []

    if supabase and uid:
        try:
            resp = supabase.table("bonus_missoes").select("*").eq("user_id", uid).eq("mes", mes_atual).order("created_at", desc=True).execute()
            bonus_list = resp.data or []
        except Exception as e:
            current_app.logger.warning("Tabela bonus_missoes não encontrada ou erro ao carregar: %s", e)
            # Retorna lista vazia se tabela não existir
            bonus_list = []

    return bonus_list

@alocacoes_bp.route("/bonus", methods=["GET", "POST"])
@login_required
def bonus():
    """Gerenciar bônus/missões do assessor"""
    if request.method == "POST":
        nome_missao = (request.form.get("nome_missao") or "").strip()
        valor_bonus = _to_float(request.form.get("valor_bonus"))
        origem = (request.form.get("origem") or "XP").strip()
        liquido_assessor = request.form.get("liquido_assessor") == "on"

        if not nome_missao:
            flash("Nome da missão é obrigatório.", "error")
            return redirect(url_for("alocacoes.bonus"))

        if origem not in ["XP", "SVN", "MB"]:
            origem = "XP"

        supabase = _get_supabase()
        uid = _uid()

        if not supabase or not uid:
            flash("Sistema indisponível ou sessão inválida.", "error")
            return redirect(url_for("alocacoes.bonus"))

        try:
            from datetime import datetime
            mes_atual = datetime.now().strftime("%Y-%m")

            # Dados básicos obrigatórios
            insert_data = {
                "user_id": uid,
                "mes": mes_atual,
                "nome_missao": nome_missao,
                "valor_bonus": valor_bonus,
                "ativo": True
            }

            # Tentar adicionar campos novos se a tabela suportar
            try:
                insert_data["origem"] = origem
                insert_data["liquido_assessor"] = liquido_assessor
            except:
                pass  # Campos novos podem não existir ainda

            supabase.table("bonus_missoes").insert(insert_data).execute()

            flash(f"Missão '{nome_missao}' cadastrada com sucesso!", "success")
            return redirect(url_for("alocacoes.bonus"))

        except Exception as e:
            current_app.logger.warning("Erro ao cadastrar bônus/missão: %s", e)
            # Tentar com campos básicos apenas
            try:
                supabase.table("bonus_missoes").insert({
                    "user_id": uid,
                    "mes": mes_atual,
                    "nome_missao": nome_missao,
                    "valor_bonus": valor_bonus,
                    "ativo": True
                }).execute()
                flash(f"Missão '{nome_missao}' cadastrada (campos básicos - execute migração SQL para funcionalidade completa).", "warning")
                return redirect(url_for("alocacoes.bonus"))
            except Exception as e2:
                current_app.logger.warning("Erro ao cadastrar bônus/missão (fallback): %s", e2)
                flash("Funcionalidade de bônus requer configuração no banco. Entre em contato com o administrador.", "error")
                return redirect(url_for("alocacoes.bonus"))

    # GET - listar bônus/missões
    bonus_list = _carregar_bonus_mes()
    total_bonus = sum(
        _calcular_valor_liquido_bonus(
            b.get("valor_bonus", 0),
            b.get("liquido_assessor", True)
        )
        for b in bonus_list if b.get("ativo", True)
    )

    return render_template(
        "alocacoes/bonus.html",
        bonus_list=bonus_list,
        total_bonus=total_bonus
    )

@alocacoes_bp.route("/bonus/<string:bonus_id>/excluir", methods=["POST"])
@login_required
def excluir_bonus(bonus_id: str):
    """Excluir bônus/missão"""
    supabase = _get_supabase()
    uid = _uid()

    if not supabase or not uid:
        flash("Sistema indisponível ou sessão inválida.", "error")
        return redirect(url_for("alocacoes.bonus"))

    try:
        supabase.table("bonus_missoes").delete().eq("id", bonus_id).eq("user_id", uid).execute()
        flash("Missão excluída com sucesso!", "success")
    except Exception as e:
        current_app.logger.warning("Erro ao excluir bônus/missão (tabela pode não existir): %s", e)
        flash("Funcionalidade de bônus requer configuração no banco.", "error")

    return redirect(url_for("alocacoes.bonus"))

@alocacoes_bp.route("/bonus/<string:bonus_id>/toggle", methods=["POST"])
@login_required
def toggle_bonus(bonus_id: str):
    """Ativar/desativar bônus/missão"""
    supabase = _get_supabase()
    uid = _uid()

    if not supabase or not uid:
        flash("Sistema indisponível ou sessão inválida.", "error")
        return redirect(url_for("alocacoes.bonus"))

    try:
        # Buscar status atual
        resp = supabase.table("bonus_missoes").select("ativo").eq("id", bonus_id).eq("user_id", uid).execute()
        if resp.data:
            ativo_atual = resp.data[0].get("ativo", True)
            novo_status = not ativo_atual

            supabase.table("bonus_missoes").update({"ativo": novo_status}).eq("id", bonus_id).eq("user_id", uid).execute()

            status_texto = "ativada" if novo_status else "desativada"
            flash(f"Missão {status_texto} com sucesso!", "success")
        else:
            flash("Missão não encontrada.", "error")

    except Exception as e:
        current_app.logger.warning("Erro ao alterar status do bônus/missão (tabela pode não existir): %s", e)
        flash("Funcionalidade de bônus requer configuração no banco.", "error")

    return redirect(url_for("alocacoes.bonus"))

@alocacoes_bp.route("/bonus/<string:bonus_id>/editar", methods=["GET", "POST"])
@login_required
def editar_bonus(bonus_id: str):
    """Editar bônus/missão"""
    supabase = _get_supabase()
    uid = _uid()

    if not supabase or not uid:
        flash("Sistema indisponível ou sessão inválida.", "error")
        return redirect(url_for("alocacoes.bonus"))

    # Buscar o bônus atual
    try:
        resp = supabase.table("bonus_missoes").select("*").eq("id", bonus_id).eq("user_id", uid).execute()
        if not resp.data:
            flash("Missão não encontrada.", "error")
            return redirect(url_for("alocacoes.bonus"))

        bonus = resp.data[0]
    except Exception as e:
        current_app.logger.warning("Erro ao buscar bônus para edição: %s", e)
        flash("Erro ao carregar missão.", "error")
        return redirect(url_for("alocacoes.bonus"))

    if request.method == "POST":
        nome_missao = (request.form.get("nome_missao") or "").strip()
        valor_bonus = _to_float(request.form.get("valor_bonus"))
        origem = (request.form.get("origem") or "XP").strip()
        liquido_assessor = request.form.get("liquido_assessor") == "on"

        if not nome_missao:
            flash("Nome da missão é obrigatório.", "error")
            return redirect(url_for("alocacoes.editar_bonus", bonus_id=bonus_id))

        if origem not in ["XP", "SVN", "MB"]:
            origem = "XP"

        try:
            # Tentar atualizar com todos os campos
            update_data = {
                "nome_missao": nome_missao,
                "valor_bonus": valor_bonus
            }

            # Adicionar campos novos apenas se a tabela suportar
            try:
                update_data["origem"] = origem
                update_data["liquido_assessor"] = liquido_assessor
            except:
                pass  # Campos novos podem não existir ainda

            supabase.table("bonus_missoes").update(update_data).eq("id", bonus_id).eq("user_id", uid).execute()

            flash("Missão atualizada com sucesso!", "success")
            return redirect(url_for("alocacoes.bonus"))

        except Exception as e:
            current_app.logger.warning("Erro ao atualizar bônus/missão: %s", e)
            # Tentar apenas com campos básicos como fallback
            try:
                supabase.table("bonus_missoes").update({
                    "nome_missao": nome_missao,
                    "valor_bonus": valor_bonus
                }).eq("id", bonus_id).eq("user_id", uid).execute()
                flash("Missão atualizada (apenas campos básicos - execute migração SQL para campos completos).", "warning")
                return redirect(url_for("alocacoes.bonus"))
            except Exception as e2:
                current_app.logger.warning("Erro ao atualizar bônus/missão (fallback): %s", e2)
                flash("Erro ao atualizar missão.", "error")
                return redirect(url_for("alocacoes.editar_bonus", bonus_id=bonus_id))

    # GET - renderizar formulário de edição
    return render_template(
        "alocacoes/editar_bonus.html",
        bonus=bonus
    )


# ---------------- METAS ESCRITÓRIO ----------------
@alocacoes_bp.route("/metas-escritorio")
@login_required
def metas_escritorio():
    """Tela para definir metas de receita por classe de produto"""
    from datetime import datetime
    
    uid = _uid()
    if not uid:
        flash("Sessão inválida.", "error")
        return redirect(url_for("alocacoes.index"))
    
    mes_atual = datetime.now().strftime("%Y-%m")
    
    # Classes de produto disponíveis (mesmas do cadastro de produtos)
    CLASSES_ATIVO = [
        "Câmbio", "COE", "Corporate", "Fundo Imobiliário", "Fundos",
        "Offshore", "Previdência", "Produto Estruturado", "Renda Fixa",
        "Renda Fixa Digital", "Renda Variável (mesa)", "Seguro de Vida",
        "Wealth Management (WM)",
    ]
    
    # Buscar metas existentes para o mês atual
    metas_existentes = {}
    try:
        supabase = _get_supabase()
        if supabase:
            resp = supabase.table("metas_escritorio_classe").select("*").eq("user_id", uid).eq("mes", mes_atual).execute()
            for meta in resp.data or []:
                classe = meta.get("classe", "")
                meta_receita = _to_float(meta.get("meta_receita", 0))
                metas_existentes[classe] = meta_receita
    except Exception as e:
        current_app.logger.exception("Erro ao buscar metas por classe")
    
    # Preparar dados para o template
    metas = []
    total_metas = 0.0
    
    for classe in CLASSES_ATIVO:
        meta_receita = metas_existentes.get(classe, 0.0)
        total_metas += meta_receita
        
        metas.append({
            "classe": classe,
            "meta_receita": meta_receita
        })
    
    return render_template(
        "alocacoes/metas_escritorio.html",
        metas=metas,
        total_metas=total_metas,
        mes_atual=mes_atual
    )


@alocacoes_bp.route("/metas-escritorio/salvar", methods=["POST"])
@login_required
def salvar_metas_escritorio():
    """Salvar metas de receita por classe"""
    supabase = _get_supabase()
    uid = _uid()
    if not uid:
        flash("Sessão inválida.", "error")
        return redirect(url_for("alocacoes.metas_escritorio"))
    
    mes = request.form.get("mes", "").strip()
    if not mes:
        flash("Mês é obrigatório.", "error")
        return redirect(url_for("alocacoes.metas_escritorio"))
    
    # Classes de produto disponíveis
    CLASSES_ATIVO = [
        "Câmbio", "COE", "Corporate", "Fundo Imobiliário", "Fundos",
        "Offshore", "Previdência", "Produto Estruturado", "Renda Fixa",
        "Renda Fixa Digital", "Renda Variável (mesa)", "Seguro de Vida",
        "Wealth Management (WM)",
    ]
    
    try:
        if not supabase:
            flash("Sistema indisponível.", "error")
            return redirect(url_for("alocacoes.metas_escritorio"))
        
        # Primeiro, excluir metas existentes para o mês
        supabase.table("metas_escritorio_classe").delete().eq("user_id", uid).eq("mes", mes).execute()
        
        # Inserir novas metas
        metas_para_inserir = []
        total_salvo = 0.0
        
        for classe in CLASSES_ATIVO:
            field_name = f"meta_{classe}"
            meta_valor = request.form.get(field_name, "").strip()
            
            try:
                meta_receita = float(meta_valor) if meta_valor else 0.0
            except ValueError:
                meta_receita = 0.0
            
            # Permitir metas zero conforme solicitado pelo usuário
            if meta_receita >= 0:
                metas_para_inserir.append({
                    "user_id": uid,
                    "mes": mes,
                    "classe": classe,
                    "meta_receita": meta_receita
                })
                total_salvo += meta_receita
        
        if metas_para_inserir:
            supabase.table("metas_escritorio_classe").insert(metas_para_inserir).execute()
        
        # Salvar a soma total na tabela metas_mensais (para compatibilidade com dashboard)
        try:
            # Primeiro, verificar se já existe uma meta para este mês
            existing_meta = supabase.table("metas_mensais").select("*").eq("user_id", uid).eq("mes", mes).execute()
            
            if existing_meta.data:
                # Atualizar meta existente
                supabase.table("metas_mensais").update({
                    "meta_receita": total_salvo
                }).eq("user_id", uid).eq("mes", mes).execute()
            else:
                # Inserir nova meta
                supabase.table("metas_mensais").insert({
                    "user_id": uid,
                    "mes": mes,
                    "meta_receita": total_salvo
                }).execute()
                
            current_app.logger.info(f"Meta total salva na tabela metas_mensais: R$ {total_salvo}")
            
        except Exception as e:
            current_app.logger.warning(f"Erro ao salvar meta total em metas_mensais: {e}")
            # Não falhar o processo principal por causa disso
        
        flash(f"Metas salvas com sucesso! Total: R$ {total_salvo:,.2f}", "success")
        
    except Exception as e:
        current_app.logger.exception("Erro ao salvar metas por classe")
        flash("Erro ao salvar metas. Tente novamente.", "error")
    
    return redirect(url_for("alocacoes.metas_escritorio"))
