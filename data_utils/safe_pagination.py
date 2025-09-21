# utils/safe_pagination.py
"""
🛡️ UTILITÁRIO DE PAGINAÇÃO SEGURA
Previne problemas de ordenação inconsistente em queries paginadas.
"""

from typing import List, Dict, Any, Optional
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class SafePaginationError(Exception):
    """Erro específico de paginação segura"""
    pass

def safe_paginated_query(
    supabase: Client,
    table_name: str,
    select_fields: str,
    filters: Dict[str, Any] = None,
    order_by: str = "id",  # SEMPRE usar ID por padrão
    desc: bool = False,
    page_size: int = 1000,
    max_pages: int = 100,  # Limite de segurança
    user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Executa query paginada com ordenação segura e validações.

    Args:
        supabase: Cliente Supabase
        table_name: Nome da tabela
        select_fields: Campos a selecionar
        filters: Filtros adicionais {campo: valor}
        order_by: Campo para ordenação (padrão: "id")
        desc: Ordenação descendente
        page_size: Tamanho da página
        max_pages: Máximo de páginas (proteção)
        user_id: ID do usuário (filtro automático)

    Returns:
        Lista com todos os registros

    Raises:
        SafePaginationError: Em caso de problemas
    """

    if order_by == "data_ref":
        logger.warning("ATENÇÃO: Usando data_ref para ordenação - pode causar inconsistências!")
        logger.warning("Recomendado: usar 'id' ou campo único")

    all_results = []
    offset = 0
    pages_processed = 0

    logger.info(f"Iniciando paginação segura: {table_name}, order_by={order_by}")

    while pages_processed < max_pages:
        try:
            # Construir query base
            query = supabase.table(table_name).select(select_fields)

            # Aplicar filtro de usuário automaticamente
            if user_id:
                query = query.eq("user_id", user_id)

            # Aplicar filtros adicionais
            if filters:
                for field, value in filters.items():
                    if isinstance(value, dict) and "operator" in value:
                        # Filtros complexos: {"operator": "gte", "value": "2025-01"}
                        op = value["operator"]
                        val = value["value"]
                        if op == "gte":
                            query = query.gte(field, val)
                        elif op == "lt":
                            query = query.lt(field, val)
                        elif op == "not_ilike":
                            query = query.not_.ilike(field, val)
                        # Adicionar outros operadores conforme necessário
                    else:
                        # Filtro simples de igualdade
                        query = query.eq(field, value)

            # Aplicar ordenação e paginação
            query = query.order(order_by, desc=desc).range(offset, offset + page_size - 1)

            # Executar query
            result = query.execute()
            page_data = result.data or []

            if not page_data:
                break

            all_results.extend(page_data)
            pages_processed += 1
            offset += page_size

            logger.debug(f"Página {pages_processed}: {len(page_data)} registros")

            # Se página não está cheia, é a última
            if len(page_data) < page_size:
                break

        except Exception as e:
            error_msg = f"Erro na paginação (página {pages_processed + 1}): {e}"
            logger.error(error_msg)
            raise SafePaginationError(error_msg) from e

    if pages_processed >= max_pages:
        logger.warning(f"Atingido limite máximo de páginas ({max_pages})")

    logger.info(f"Paginação concluída: {len(all_results)} registros em {pages_processed} páginas")

    return all_results

def safe_sum_field(
    supabase: Client,
    table_name: str,
    sum_field: str,
    filters: Dict[str, Any] = None,
    user_id: Optional[str] = None
) -> float:
    """
    Soma um campo de forma segura usando paginação.

    Args:
        supabase: Cliente Supabase
        table_name: Nome da tabela
        sum_field: Campo a somar
        filters: Filtros para aplicar
        user_id: ID do usuário

    Returns:
        Soma total do campo
    """

    # Buscar apenas o campo necessário
    records = safe_paginated_query(
        supabase=supabase,
        table_name=table_name,
        select_fields=sum_field,
        filters=filters,
        user_id=user_id
    )

    # Somar valores
    total = 0.0
    for record in records:
        value = record.get(sum_field, 0)
        if value is not None:
            try:
                total += float(value)
            except (ValueError, TypeError):
                logger.warning(f"Valor inválido para soma: {value}")
                continue

    return total

# Exemplo de uso:
"""
from utils.safe_pagination import safe_paginated_query, safe_sum_field

# Buscar receitas de fevereiro
receitas = safe_paginated_query(
    supabase=supabase,
    table_name="receita_itens",
    select_fields="data_ref, cliente_codigo, comissao_escritorio",
    filters={
        "data_ref": "2025-02",
        "familia": {"operator": "not_ilike", "value": "%administrativo%"}
    },
    user_id=user_id
)

# Somar comissões de fevereiro
total = safe_sum_field(
    supabase=supabase,
    table_name="receita_itens",
    sum_field="comissao_escritorio",
    filters={
        "data_ref": "2025-02",
        "familia": {"operator": "not_ilike", "value": "%administrativo%"}
    },
    user_id=user_id
)
"""