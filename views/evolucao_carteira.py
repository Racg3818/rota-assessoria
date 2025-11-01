from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from utils import login_required
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import calendar

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
        current_app.logger.debug("EVOLUCAO_CARTEIRA: Cliente Supabase não disponível (usuário não autenticado)")
    return client

def _uid():
    """Retorna o user_id do usuário logado"""
    from security_middleware import get_current_user_id
    return get_current_user_id()

def _to_float(value):
    """Converte string para float, tratando vírgulas e pontos
    Suporta valores negativos (ex: captação negativa = saídas/resgates)
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Remove espaços, pontos (separadores de milhar) e substitui vírgula por ponto
        # Preserva o sinal negativo
        value = str(value).strip().replace(".", "").replace(",", ".")
        return float(value) if value else 0.0
    except (ValueError, AttributeError):
        return 0.0

def _get_ciclo_avaliacao() -> Tuple[int, int, int, int]:
    """
    Retorna o ciclo de avaliação atual (Nov-Out)
    Retorna: (ano_inicio, mes_inicio, ano_fim, mes_fim)
    """
    hoje = datetime.now()
    mes_atual = hoje.month
    ano_atual = hoje.year

    # Se estamos entre Janeiro e Outubro, o ciclo começou em Novembro do ano anterior
    if mes_atual < 11:
        ano_inicio = ano_atual - 1
        mes_inicio = 11
        ano_fim = ano_atual
        mes_fim = 10
    else:
        # Se estamos em Novembro ou Dezembro, o ciclo começa este ano
        ano_inicio = ano_atual
        mes_inicio = 11
        ano_fim = ano_atual + 1
        mes_fim = 10

    return (ano_inicio, mes_inicio, ano_fim, mes_fim)

def _gerar_meses_ciclo() -> List[Dict]:
    """Gera a lista de meses do ciclo de avaliação"""
    ano_inicio, mes_inicio, ano_fim, mes_fim = _get_ciclo_avaliacao()

    meses = []

    # De Novembro até Dezembro do ano de início
    for mes in range(mes_inicio, 13):
        meses.append({
            'ano': ano_inicio,
            'mes': mes,
            'nome': calendar.month_name[mes]
        })

    # De Janeiro até Outubro do ano de fim
    for mes in range(1, mes_fim + 1):
        meses.append({
            'ano': ano_fim,
            'mes': mes,
            'nome': calendar.month_name[mes]
        })

    return meses

evolucao_carteira_bp = Blueprint('evolucao_carteira', __name__, url_prefix='/clientes/evolucao-carteira')

# ============ PÁGINA PRINCIPAL ============
@evolucao_carteira_bp.route('/', methods=['GET'])
@login_required
def index():
    """Página principal de Evolução de Carteira"""
    supabase = _get_supabase()
    uid = _uid()

    if not supabase or not uid:
        flash("Sistema indisponível ou sessão inválida", "error")
        return redirect(url_for('dash.dashboard'))

    # Obter mês e ano da URL ou usar mês atual
    hoje = datetime.now()
    ano = int(request.args.get('ano', hoje.year))
    mes = int(request.args.get('mes', hoje.month))

    try:
        # Buscar metas do mês
        metas = supabase.table("metas_evolucao_carteira")\
            .select("*")\
            .eq("user_id", uid)\
            .eq("ano", ano)\
            .eq("mes", mes)\
            .execute()

        metas_data = metas.data[0] if metas.data else {
            'meta_captacao_svn': 0,
            'meta_captacao_pessoal': 0,
            'crescimento_organico_anual': 0
        }

        # Buscar dados semanais do mês
        semanas = supabase.table("evolucao_carteira")\
            .select("*")\
            .eq("user_id", uid)\
            .eq("ano", ano)\
            .eq("mes", mes)\
            .order("semana")\
            .execute()

        # Buscar NET total do usuário
        net_total = _get_net_total(supabase, uid)

        # Preparar dados para o template
        semanas_data = semanas.data if semanas.data else []

        # Garantir que temos 5 semanas (algumas podem estar vazias)
        semanas_completas = []
        for i in range(1, 6):
            semana_existente = next((s for s in semanas_data if s.get('semana') == i), None)
            if semana_existente:
                semanas_completas.append(semana_existente)
            else:
                # Criar semana vazia
                semanas_completas.append({
                    'semana': i,
                    'captacao_semana': 0,
                    'forecast_semana': 0,
                    'churn_semana': 0
                })

        # Calcular métricas
        metricas = _calcular_metricas(semanas_completas, metas_data, net_total)

        # Dados para o gráfico
        grafico_data = _preparar_dados_grafico(semanas_completas, metas_data)

        # Dados para o gráfico de evolução do NET
        crescimento_organico = _to_float(metas_data.get('crescimento_organico_anual', 0))
        grafico_net_data = _preparar_dados_grafico_net(semanas_completas, net_total, crescimento_organico)

        # Gerar lista de meses do ciclo
        meses_ciclo = _gerar_meses_ciclo()

        return render_template(
            'evolucao_carteira.html',
            semanas=semanas_completas,
            metas=metas_data,
            metricas=metricas,
            grafico_data=grafico_data,
            grafico_net_data=grafico_net_data,
            ano=ano,
            mes=mes,
            mes_nome=calendar.month_name[mes],
            net_total=net_total,
            meses_ciclo=meses_ciclo
        )

    except Exception as e:
        current_app.logger.error(f"Erro ao carregar evolução de carteira: {e}")
        flash("Erro ao carregar dados de evolução de carteira", "error")
        return redirect(url_for('dash.dashboard'))

# ============ API: SALVAR/ATUALIZAR METAS MENSAIS ============
@evolucao_carteira_bp.route('/api/salvar-metas', methods=['POST'])
@login_required
def salvar_metas():
    """API para salvar ou atualizar metas mensais"""
    supabase = _get_supabase()
    uid = _uid()

    if not supabase or not uid:
        return jsonify({"success": False, "message": "Sistema indisponível"}), 400

    try:
        # Extrair dados do formulário
        ano = int(request.form.get('ano'))
        mes = int(request.form.get('mes'))

        dados = {
            'user_id': uid,
            'ano': ano,
            'mes': mes,
            'meta_captacao_svn': _to_float(request.form.get('meta_captacao_svn', 0)),
            'meta_captacao_pessoal': _to_float(request.form.get('meta_captacao_pessoal', 0)),
            'crescimento_organico_anual': _to_float(request.form.get('crescimento_organico_anual', 0))
        }

        # Validações
        if not (1 <= mes <= 12):
            return jsonify({"success": False, "message": "Mês inválido"}), 400

        if not (0 <= dados['crescimento_organico_anual'] <= 20):
            return jsonify({"success": False, "message": "Crescimento orgânico deve estar entre 0% e 20%"}), 400

        # Verificar se já existe registro para este mês
        existing = supabase.table("metas_evolucao_carteira")\
            .select("id")\
            .eq("user_id", uid)\
            .eq("ano", ano)\
            .eq("mes", mes)\
            .execute()

        if existing.data:
            # Atualizar registro existente
            registro_id = existing.data[0]['id']
            dados_update = {k: v for k, v in dados.items() if k not in ['user_id', 'ano', 'mes']}

            supabase.table("metas_evolucao_carteira")\
                .update(dados_update)\
                .eq("id", registro_id)\
                .eq("user_id", uid)\
                .execute()

            message = "Metas do mês atualizadas com sucesso"
        else:
            # Inserir novo registro
            supabase.table("metas_evolucao_carteira")\
                .insert(dados)\
                .execute()

            message = "Metas do mês salvas com sucesso"

        return jsonify({
            "success": True,
            "message": message
        })

    except Exception as e:
        current_app.logger.error(f"Erro ao salvar metas: {e}")
        return jsonify({
            "success": False,
            "message": "Erro ao salvar metas"
        }), 500

# ============ API: SALVAR/ATUALIZAR DADOS DE SEMANA ============
@evolucao_carteira_bp.route('/api/salvar-semana', methods=['POST'])
@login_required
def salvar_semana():
    """API para salvar ou atualizar dados de uma semana"""
    supabase = _get_supabase()
    uid = _uid()

    if not supabase or not uid:
        return jsonify({"success": False, "message": "Sistema indisponível"}), 400

    try:
        # Extrair dados do formulário
        ano = int(request.form.get('ano'))
        mes = int(request.form.get('mes'))
        semana = int(request.form.get('semana'))

        # Debug: log dos valores recebidos
        captacao_raw = request.form.get('captacao_semana', 0)
        forecast_raw = request.form.get('forecast_semana', 0)
        churn_raw = request.form.get('churn_semana', 0)

        current_app.logger.info(f"EVOLUCAO: Valores recebidos - Captação: '{captacao_raw}', Forecast: '{forecast_raw}', Churn: '{churn_raw}'")

        dados = {
            'user_id': uid,
            'ano': ano,
            'mes': mes,
            'semana': semana,
            'captacao_semana': _to_float(captacao_raw),
            'forecast_semana': _to_float(forecast_raw),
            'churn_semana': _to_float(churn_raw)
        }

        current_app.logger.info(f"EVOLUCAO: Valores convertidos - Captação: {dados['captacao_semana']}, Forecast: {dados['forecast_semana']}, Churn: {dados['churn_semana']}")

        # Validações
        if not (1 <= mes <= 12):
            return jsonify({"success": False, "message": "Mês inválido"}), 400

        if not (1 <= semana <= 5):
            return jsonify({"success": False, "message": "Semana inválida"}), 400

        # Verificar se já existe registro para esta semana
        existing = supabase.table("evolucao_carteira")\
            .select("id")\
            .eq("user_id", uid)\
            .eq("ano", ano)\
            .eq("mes", mes)\
            .eq("semana", semana)\
            .execute()

        if existing.data:
            # Atualizar registro existente
            registro_id = existing.data[0]['id']
            dados_update = {k: v for k, v in dados.items() if k not in ['user_id', 'ano', 'mes', 'semana']}

            supabase.table("evolucao_carteira")\
                .update(dados_update)\
                .eq("id", registro_id)\
                .eq("user_id", uid)\
                .execute()

            message = "Dados da semana atualizados com sucesso"
        else:
            # Inserir novo registro
            supabase.table("evolucao_carteira")\
                .insert(dados)\
                .execute()

            message = "Dados da semana salvos com sucesso"

        return jsonify({
            "success": True,
            "message": message
        })

    except Exception as e:
        current_app.logger.error(f"Erro ao salvar dados da semana: {e}")
        return jsonify({
            "success": False,
            "message": "Erro ao salvar dados"
        }), 500

# ============ API: OBTER MÉTRICAS ATUALIZADAS ============
@evolucao_carteira_bp.route('/api/metricas', methods=['GET'])
@login_required
def obter_metricas():
    """API para obter métricas calculadas do mês"""
    supabase = _get_supabase()
    uid = _uid()

    if not supabase or not uid:
        return jsonify({"success": False, "message": "Sistema indisponível"}), 400

    try:
        ano = int(request.args.get('ano'))
        mes = int(request.args.get('mes'))

        # Buscar metas do mês
        metas = supabase.table("metas_evolucao_carteira")\
            .select("*")\
            .eq("user_id", uid)\
            .eq("ano", ano)\
            .eq("mes", mes)\
            .execute()

        metas_data = metas.data[0] if metas.data else {
            'meta_captacao_svn': 0,
            'meta_captacao_pessoal': 0,
            'crescimento_organico_anual': 0
        }

        # Buscar dados semanais do mês
        semanas = supabase.table("evolucao_carteira")\
            .select("*")\
            .eq("user_id", uid)\
            .eq("ano", ano)\
            .eq("mes", mes)\
            .execute()

        # Buscar NET total
        net_total = _get_net_total(supabase, uid)

        semanas_data = semanas.data if semanas.data else []
        metricas = _calcular_metricas(semanas_data, metas_data, net_total)

        return jsonify({
            "success": True,
            "metricas": metricas
        })

    except Exception as e:
        current_app.logger.error(f"Erro ao calcular métricas: {e}")
        return jsonify({
            "success": False,
            "message": "Erro ao calcular métricas"
        }), 500

# ============ FUNÇÕES AUXILIARES ============

def _get_net_total(supabase, uid: str) -> float:
    """Obtém o NET total do usuário (soma de todos os clientes)"""
    try:
        # Buscar todos os clientes do usuário
        result = supabase.table("clientes")\
            .select("net_total")\
            .eq("user_id", uid)\
            .execute()

        if not result.data:
            return 0.0

        # Somar todos os NET totals
        total = sum(_to_float(cliente.get('net_total', 0)) for cliente in result.data)
        return total

    except Exception as e:
        current_app.logger.error(f"Erro ao buscar NET total: {e}")
        return 0.0

def _calcular_metricas(semanas: List[Dict], metas: Dict, net_total: float) -> Dict:
    """Calcula as métricas principais baseadas nos dados das semanas e metas"""

    # Inicializar totais
    total_captacao = 0.0
    total_churn = 0.0

    for semana in semanas:
        total_captacao += _to_float(semana.get('captacao_semana', 0))
        total_churn += _to_float(semana.get('churn_semana', 0))

    # Obter metas
    meta_svn = _to_float(metas.get('meta_captacao_svn', 0))
    meta_pessoal = _to_float(metas.get('meta_captacao_pessoal', 0))

    # Calcular percentuais
    perc_churn = (total_churn / net_total * 100) if net_total > 0 else 0
    perc_meta_svn = (total_captacao / meta_svn * 100) if meta_svn > 0 else 0
    perc_meta_pessoal = (total_captacao / meta_pessoal * 100) if meta_pessoal > 0 else 0

    return {
        'total_captacao': total_captacao,
        'total_churn': total_churn,
        'perc_churn': perc_churn,
        'perc_meta_svn': perc_meta_svn,
        'perc_meta_pessoal': perc_meta_pessoal,
        'meta_svn': meta_svn,
        'meta_pessoal': meta_pessoal
    }

def _preparar_dados_grafico(semanas: List[Dict], metas: Dict) -> Dict:
    """Prepara os dados para o gráfico de evolução semanal"""

    labels = []
    captacao_realizada = []
    captacao_acumulada = []
    projecao_acumulada = []
    meta_acumulada = []

    acumulado_captacao = 0.0
    acumulado_projecao = 0.0
    meta_mensal = _to_float(metas.get('meta_captacao_pessoal', 0))

    for semana in semanas:
        semana_num = semana.get('semana', 0)
        labels.append(f"Semana {semana_num}")

        # Captação da semana
        captacao_semana = _to_float(semana.get('captacao_semana', 0))
        captacao_realizada.append(captacao_semana)

        # Acumular captação
        acumulado_captacao += captacao_semana
        captacao_acumulada.append(acumulado_captacao)

        # Projeção: captação + forecast - churn
        forecast_semana = _to_float(semana.get('forecast_semana', 0))
        churn_semana = _to_float(semana.get('churn_semana', 0))
        projecao_semana = captacao_semana + forecast_semana - churn_semana
        acumulado_projecao += projecao_semana
        projecao_acumulada.append(acumulado_projecao)

        # Meta acumulada proporcional (meta / 5 semanas * número da semana)
        meta_proporcional = (meta_mensal / 5) * semana_num if meta_mensal > 0 else 0
        meta_acumulada.append(meta_proporcional)

    return {
        'labels': labels,
        'captacao_realizada': captacao_realizada,
        'captacao_acumulada': captacao_acumulada,
        'projecao_acumulada': projecao_acumulada,
        'meta_acumulada': meta_acumulada
    }

def _preparar_dados_grafico_net(semanas: List[Dict], net_atual: float, crescimento_organico_anual: float = 0) -> Dict:
    """
    Prepara os dados para o gráfico de evolução do NET
    Mostra como o NET evoluiria semana a semana se o usuário concretizar:
    captação + forecast - churn + crescimento orgânico

    O crescimento orgânico é distribuído proporcionalmente por semana:
    - Anual dividido por 52 semanas = crescimento semanal
    - Aplicado sobre o NET atual de cada semana
    """
    labels = []
    net_projecao = []

    net_acumulado = net_atual  # Começa com o NET atual

    # Calcular crescimento orgânico semanal (percentual)
    # Se temos 5 semanas no mês, distribuímos o crescimento anual proporcionalmente
    crescimento_semanal_percent = (crescimento_organico_anual / 100) / 52  # Por semana

    for semana in semanas:
        semana_num = semana.get('semana', 0)
        labels.append(f"Semana {semana_num}")

        # Calcular o impacto da semana: captação + forecast - churn
        captacao = _to_float(semana.get('captacao_semana', 0))
        forecast = _to_float(semana.get('forecast_semana', 0))
        churn = _to_float(semana.get('churn_semana', 0))

        # Crescimento orgânico sobre o NET atual
        crescimento_organico_semana = net_acumulado * crescimento_semanal_percent

        # Impacto total da semana
        impacto_semana = captacao + forecast - churn + crescimento_organico_semana
        net_acumulado += impacto_semana

        net_projecao.append(net_acumulado)

    return {
        'labels': labels,
        'net_projecao': net_projecao,
        'net_inicial': net_atual,
        'crescimento_organico_anual': crescimento_organico_anual
    }
