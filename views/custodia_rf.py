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

custodia_rf_bp = Blueprint('custodia_rf', __name__, url_prefix='/custodia-rf')


def parse_custodia_rf_file(file_storage, data_ref: str) -> list[dict]:
    """
    Parser do arquivo Custódia.xlsx (Renda Fixa)

    Estrutura esperada:
    - Cód. Assessor
    - Cód. conta
    - Ticker
    - Nome papel
    - Custódia
    - Vencimento
    - indexador
    - Taxa cliente

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
                # Converter Vencimento para date
                vencimento = row_dict.get('Vencimento')
                if vencimento:
                    if isinstance(vencimento, datetime):
                        vencimento = vencimento.date()
                    elif isinstance(vencimento, str):
                        # Tentar converter string para data
                        try:
                            vencimento = datetime.strptime(vencimento.split()[0], '%d/%m/%Y').date()
                        except:
                            vencimento = None
                else:
                    vencimento = None

                # Converter Custódia para numérico
                custodia = row_dict.get('Custódia')
                if custodia is not None:
                    try:
                        custodia = float(custodia)
                    except:
                        custodia = 0.0
                else:
                    custodia = 0.0

                # Converter Taxa cliente para numérico
                taxa_cliente = row_dict.get('Taxa cliente')
                if taxa_cliente is not None:
                    try:
                        taxa_cliente = float(taxa_cliente)
                    except:
                        taxa_cliente = None
                else:
                    taxa_cliente = None

                # Converter Cód. conta para inteiro
                cod_conta = row_dict.get('Cód. conta')
                if cod_conta is not None:
                    try:
                        cod_conta = int(cod_conta)
                    except:
                        current_app.logger.warning(f"Código de conta inválido na linha {row_idx}: {cod_conta}")
                        continue
                else:
                    current_app.logger.warning(f"Código de conta ausente na linha {row_idx}")
                    continue

                # Montar registro
                record = {
                    'cod_assessor': str(row_dict.get('Cód. Assessor', '')).strip(),
                    'cod_conta': cod_conta,
                    'ticker': str(row_dict.get('Ticker', '')).strip() if row_dict.get('Ticker') else None,
                    'nome_papel': str(row_dict.get('Nome papel', '')).strip() if row_dict.get('Nome papel') else None,
                    'custodia': custodia,
                    'vencimento': vencimento.isoformat() if vencimento else None,
                    'indexador': str(row_dict.get('indexador', '')).strip() if row_dict.get('indexador') else None,
                    'taxa_cliente': taxa_cliente,
                    'data_referencia': datetime.strptime(data_ref, '%Y-%m').date().isoformat(),
                }

                rows.append(record)

            except Exception as e:
                current_app.logger.warning(f"Erro ao processar linha {row_idx}: {e}")
                continue

        wb.close()

    except Exception as e:
        current_app.logger.error(f"Erro ao fazer parse do arquivo Custódia RF: {e}")
        raise

    return rows


@custodia_rf_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    """Tela de importação do arquivo Custódia RF"""

    if request.method == 'POST':
        competencia = (request.form.get('competencia') or '').strip()
        if not competencia:
            flash('Informe a competência no formato YYYY-MM.', 'error')
            return redirect(url_for('custodia_rf.index'))

        f = request.files.get('arquivo')
        if not f or f.filename == '':
            flash('Selecione o arquivo Custódia.xlsx.', 'error')
            return redirect(url_for('custodia_rf.index'))

        try:
            if not get_supabase_client:
                flash('Sistema indisponível. Tente novamente mais tarde.', 'error')
                return redirect(url_for('custodia_rf.index'))

            supabase = get_supabase_client()

            # Obter user_id
            u = session.get("user") or {}
            uid = u.get("id") or u.get("supabase_user_id")
            if not uid:
                flash("Sessão inválida: não foi possível identificar o usuário.", "error")
                return redirect(url_for('custodia_rf.index'))

            # 1) Parser do arquivo
            rows = parse_custodia_rf_file(f, data_ref=competencia)

            if not rows:
                flash('Nenhum dado encontrado no arquivo.', 'error')
                return redirect(url_for('custodia_rf.index'))

            # 2) Anexar user_id a cada linha
            rows_with_uid = [{**r, "user_id": uid} for r in rows]

            # 3) Verificar se já existem dados para o usuário
            existing_data = supabase.table("custodia_rf").select("data_referencia").eq("user_id", uid).limit(1).execute()

            # 4) Se existir dados, comparar data_referencia
            nova_data_ref = datetime.strptime(competencia, '%Y-%m').date()

            if existing_data.data:
                # Pegar a data de referência mais recente no banco
                data_existente = existing_data.data[0].get('data_referencia')
                data_existente_parsed = datetime.strptime(data_existente, '%Y-%m-%d').date()

                # Se o novo arquivo for mais antigo ou igual, não substituir
                if nova_data_ref <= data_existente_parsed:
                    flash(f'ℹ️ Dados não importados. A data de referência do arquivo ({competencia}) é mais antiga ou igual aos dados já existentes ({data_existente_parsed.strftime("%Y-%m")}).', 'warning')
                    return redirect(url_for('custodia_rf.index'))

                # Se o novo arquivo for mais recente, deletar todos os dados antigos
                current_app.logger.info(f"[Import Custódia RF] Substituindo dados antigos ({data_existente_parsed}) por novos ({nova_data_ref})")
                supabase.table("custodia_rf").delete().eq("user_id", uid).execute()

            # 5) Inserir novos dados em chunks
            CHUNK = 500
            total_inserted = 0
            for i in range(0, len(rows_with_uid), CHUNK):
                chunk = rows_with_uid[i:i+CHUNK]
                supabase.table("custodia_rf").insert(chunk).execute()
                total_inserted += len(chunk)

            current_app.logger.info(
                f"[Import Custódia RF {competencia} uid={uid}] {total_inserted} linhas importadas"
            )

            # Invalidar caches
            if invalidate_user_cache:
                invalidate_user_cache('custodia_rf_data')

            flash(f'✅ {total_inserted} registros importados com sucesso para {competencia}!', 'success')
            return redirect(url_for('custodia_rf.index'))

        except Exception as e:
            current_app.logger.exception(f"Erro ao importar Custódia RF: {e}")
            flash(f'❌ Erro ao importar arquivo: {str(e)}', 'error')
            return redirect(url_for('custodia_rf.index'))

    # GET - Exibir formulário
    default_month = datetime.today().strftime('%Y-%m')
    return render_template('custodia_rf/index.html', default_month=default_month)
