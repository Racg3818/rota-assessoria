from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from utils import login_required
from datetime import datetime
import openpyxl
from io import BytesIO

# Supabase obrigatório
try:
    from supabase_client import get_supabase_client
except Exception:
    get_supabase_client = None

try:
    from cache_manager import invalidate_user_cache
except Exception:
    invalidate_user_cache = None

diversificador_bp = Blueprint('diversificador', __name__, url_prefix='/diversificador')


def parse_diversificador_file(file_storage, data_ref: str) -> list[dict]:
    """
    Parser do arquivo Diversificador.xlsx

    Estrutura esperada:
    - Assessor
    - Cliente
    - Produto
    - Sub Produto
    - Produto em Garantia
    - CNPJ Fundo
    - Ativo
    - Emissor
    - Data de Vencimento
    - Quantidade
    - NET
    - Data

    Returns:
        Lista de dicionários com os dados parseados
    """
    rows = []

    try:
        # Ler arquivo Excel
        file_content = BytesIO(file_storage.read())
        wb = openpyxl.load_workbook(file_content, data_only=True)
        sheet = wb.active

        # Obter cabeçalhos
        headers = [cell.value for cell in sheet[1]]

        # Processar linhas
        for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(row):  # Pular linhas vazias
                continue

            row_dict = {}
            for col_idx, value in enumerate(row):
                if col_idx < len(headers):
                    header = headers[col_idx]
                    row_dict[header] = value

            # Extrair e normalizar dados
            try:
                # Converter Data de Vencimento para date
                data_vencimento = row_dict.get('Data de Vencimento')
                if data_vencimento:
                    if isinstance(data_vencimento, datetime):
                        data_vencimento = data_vencimento.date()
                    elif isinstance(data_vencimento, str):
                        # Tentar converter string para data
                        try:
                            data_vencimento = datetime.strptime(data_vencimento.split()[0], '%d/%m/%Y').date()
                        except:
                            data_vencimento = None
                else:
                    data_vencimento = None

                # Converter Data para date
                data = row_dict.get('Data')
                if data:
                    if isinstance(data, datetime):
                        data = data.date()
                    elif isinstance(data, str):
                        try:
                            data = datetime.strptime(data.split()[0], '%d/%m/%Y').date()
                        except:
                            data = None
                else:
                    data = None

                # Converter quantidade e NET para numérico
                quantidade = row_dict.get('Quantidade')
                if quantidade is not None:
                    try:
                        quantidade = float(quantidade)
                    except:
                        quantidade = 0.0
                else:
                    quantidade = 0.0

                net = row_dict.get('NET')
                if net is not None:
                    try:
                        net = float(net)
                    except:
                        net = 0.0
                else:
                    net = 0.0

                # Montar registro
                record = {
                    'assessor': str(row_dict.get('Assessor', '')),
                    'cliente': str(row_dict.get('Cliente', '')),
                    'produto': str(row_dict.get('Produto', '')),
                    'sub_produto': str(row_dict.get('Sub Produto', '')),
                    'produto_em_garantia': str(row_dict.get('Produto em Garantia', '')),
                    'cnpj_fundo': str(row_dict.get('CNPJ Fundo', '')) if row_dict.get('CNPJ Fundo') else None,
                    'ativo': str(row_dict.get('Ativo', '')),
                    'emissor': str(row_dict.get('Emissor', '')),
                    'data_vencimento': data_vencimento.isoformat() if data_vencimento else None,
                    'quantidade': quantidade,
                    'net': net,
                    'data_referencia': datetime.strptime(data_ref, '%Y-%m').date().isoformat(),
                }

                rows.append(record)

            except Exception as e:
                current_app.logger.warning(f"Erro ao processar linha {row_idx}: {e}")
                continue

        wb.close()

    except Exception as e:
        current_app.logger.error(f"Erro ao fazer parse do arquivo Diversificador: {e}")
        raise

    return rows


@diversificador_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    """Tela de importação do arquivo Diversificador"""

    if request.method == 'POST':
        competencia = (request.form.get('competencia') or '').strip()
        if not competencia:
            flash('Informe a competência no formato YYYY-MM.', 'error')
            return redirect(url_for('diversificador.index'))

        f = request.files.get('arquivo')
        if not f or f.filename == '':
            flash('Selecione o arquivo Diversificador.xlsx.', 'error')
            return redirect(url_for('diversificador.index'))

        try:
            if not get_supabase_client:
                flash('Sistema indisponível. Tente novamente mais tarde.', 'error')
                return redirect(url_for('diversificador.index'))

            supabase = get_supabase_client()

            # Obter user_id
            u = session.get("user") or {}
            uid = u.get("id") or u.get("supabase_user_id")
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for('diversificador.index'))

            # 1) Parser do arquivo
            rows = parse_diversificador_file(f, data_ref=competencia)

            if not rows:
                flash('Nenhum dado encontrado no arquivo.', 'error')
                return redirect(url_for('diversificador.index'))

            # 2) Anexar user_id a cada linha
            rows_with_uid = [{**r, "user_id": uid} for r in rows]

            # 3) Deletar dados existentes da mesma competência
            data_ref = datetime.strptime(competencia, '%Y-%m').date()
            supabase.table("diversificador").delete().eq("data_referencia", str(data_ref)).eq("user_id", uid).execute()

            # 4) Inserir novos dados em chunks
            CHUNK = 500
            total_inserted = 0
            for i in range(0, len(rows_with_uid), CHUNK):
                chunk = rows_with_uid[i:i+CHUNK]
                supabase.table("diversificador").insert(chunk).execute()
                total_inserted += len(chunk)

            current_app.logger.info(
                f"[Import Diversificador {competencia} uid={uid}] {total_inserted} linhas importadas"
            )

            # Invalidar caches
            if invalidate_user_cache:
                invalidate_user_cache('diversificador_data')

            flash(f'✅ {total_inserted} registros importados com sucesso para {competencia}!', 'success')
            return redirect(url_for('diversificador.index'))

        except Exception as e:
            current_app.logger.exception(f"Erro ao importar Diversificador: {e}")
            flash(f'❌ Erro ao importar arquivo: {str(e)}', 'error')
            return redirect(url_for('diversificador.index'))

    # GET - Exibir formulário
    default_month = datetime.today().strftime('%Y-%m')
    return render_template('diversificador/index.html', default_month=default_month)
