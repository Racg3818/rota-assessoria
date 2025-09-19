"""
Sistema de dados fallback para quando o Supabase não está disponível.
Fornece dados básicos para manter o sistema funcionando.
"""

from flask import current_app
from typing import List, Dict, Any
import json
import os

def get_fallback_clientes(user_id: str) -> List[Dict]:
    """Retorna lista de clientes fallback para o usuário."""
    return [
        {
            'id': 1,
            'nome': 'Cliente Demo',
            'modelo': 'assessoria',
            'repasse': 80.0,
            'net_total': 100000.00,
            'net_xp': 50000.00,
            'net_xp_global': 60000.00,
            'net_mb': 40000.00,
            'codigo_xp': '123456',
            'codigo_mb': '654321',
            'user_id': user_id,
            'is_fallback': True
        }
    ]

def get_fallback_produtos(user_id: str) -> List[Dict]:
    """Retorna lista de produtos fallback para o usuário."""
    return [
        {
            'id': 1,
            'nome': 'Fundo Demo',
            'classe': 'renda_fixa',
            'roa_pct': 1.2,
            'em_campanha': False,
            'campanha_mes': None,
            'user_id': user_id,
            'is_fallback': True
        },
        {
            'id': 2,
            'nome': 'Ação Demo',
            'classe': 'renda_variavel',
            'roa_pct': 0.8,
            'em_campanha': True,
            'campanha_mes': '2025-09',
            'user_id': user_id,
            'is_fallback': True
        }
    ]

def get_fallback_alocacoes(user_id: str) -> List[Dict]:
    """Retorna lista de alocações fallback para o usuário."""
    return [
        {
            'id': 1,
            'cliente_id': 1,
            'produto_id': 1,
            'valor': 50000.00,
            'percentual': 50.0,
            'efetivada': True,
            'user_id': user_id,
            'created_at': '2025-09-01T00:00:00',
            'is_fallback': True,
            'cliente': {'nome': 'Cliente Demo', 'modelo': 'assessoria', 'repasse': 80.0},
            'produto': {'nome': 'Fundo Demo', 'roa_pct': 1.2}
        }
    ]

def get_fallback_metas_mensais(user_id: str) -> List[Dict]:
    """Retorna metas mensais fallback para o usuário."""
    return [
        {
            'id': 1,
            'mes': '2025-09',
            'meta_receita': 100000.00,
            'user_id': user_id,
            'is_fallback': True
        }
    ]

def get_fallback_receita_itens(user_id: str) -> List[Dict]:
    """Retorna itens de receita fallback para o usuário."""
    return [
        {
            'id': 1,
            'data_ref': '2025-09-01',
            'cliente_codigo': '123456',
            'produto': 'Fundo Demo',
            'familia': 'RF',
            'valor_bruto': 1200.00,
            'valor_liquido': 960.00,
            'user_id': user_id,
            'is_fallback': True
        }
    ]

class FallbackSupabaseClient:
    """Cliente Supabase fallback que usa dados locais."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.fallback_data = {
            'clientes': get_fallback_clientes(user_id),
            'produtos': get_fallback_produtos(user_id),
            'alocacoes': get_fallback_alocacoes(user_id),
            'metas_mensais': get_fallback_metas_mensais(user_id),
            'receita_itens': get_fallback_receita_itens(user_id),
        }

    def table(self, table_name: str):
        """Simula a interface table() do Supabase."""
        return FallbackTable(table_name, self.fallback_data.get(table_name, []), self.user_id)

class FallbackTable:
    """Simula uma tabela Supabase com dados fallback."""

    def __init__(self, table_name: str, data: List[Dict], user_id: str):
        self.table_name = table_name
        self.data = data
        self.user_id = user_id
        self.filters = []
        self.selected_columns = '*'
        self.order_by_field = None
        self.limit_count = None

    def select(self, columns: str = '*'):
        """Simula select()."""
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: Any):
        """Simula filtro eq()."""
        self.filters.append(('eq', column, value))
        return self

    def order(self, column: str, desc: bool = False):
        """Simula order()."""
        self.order_by_field = (column, desc)
        return self

    def limit(self, count: int):
        """Simula limit()."""
        self.limit_count = count
        return self

    def execute(self):
        """Executa a query simulada."""
        # Aplicar filtros
        filtered_data = self.data[:]

        for filter_type, column, value in self.filters:
            if filter_type == 'eq':
                filtered_data = [item for item in filtered_data if item.get(column) == value]

        # Aplicar ordenação
        if self.order_by_field:
            column, desc = self.order_by_field
            filtered_data.sort(key=lambda x: x.get(column, ''), reverse=desc)

        # Aplicar limit
        if self.limit_count:
            filtered_data = filtered_data[:self.limit_count]

        # Log da operação fallback
        if current_app:
            current_app.logger.info("FALLBACK: Query em %s retornou %d registros para user_id: %s",
                                   self.table_name, len(filtered_data), self.user_id)

        # Retornar no formato esperado pelo Supabase
        return type('Result', (), {'data': filtered_data})()

def create_fallback_client(user_id: str):
    """Cria um cliente Supabase fallback para o usuário."""
    if current_app:
        current_app.logger.warning("FALLBACK: Criando cliente fallback para user_id: %s", user_id)

    return FallbackSupabaseClient(user_id)