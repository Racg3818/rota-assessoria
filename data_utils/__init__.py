# data_utils/__init__.py
"""
🛠️ UTILITÁRIOS DE INTEGRIDADE E PAGINAÇÃO SEGURA
Ferramentas para garantir consistência de dados e prevenir problemas de paginação.
"""

__version__ = "1.0.0"

# Importações principais para facilitar uso
try:
    from .safe_pagination import safe_paginated_query, safe_sum_field, SafePaginationError
    from .data_integrity import DataIntegrityValidator, DataIntegrityError
    from .monitoring import ReceiptaMonitor, MonitoringAlert

    __all__ = [
        'safe_paginated_query',
        'safe_sum_field',
        'SafePaginationError',
        'DataIntegrityValidator',
        'DataIntegrityError',
        'ReceiptaMonitor',
        'MonitoringAlert'
    ]

except ImportError as e:
    # Em caso de dependências faltando, pelo menos inicializar o pacote
    print(f"Aviso: Algumas funcionalidades podem não estar disponíveis: {e}")
    __all__ = []