# utils/data_integrity.py
"""
🔍 SISTEMA DE VALIDAÇÃO DE INTEGRIDADE DE DADOS
Monitora e valida cálculos críticos para detectar inconsistências.
"""

from typing import Dict, List, Tuple, Optional
from supabase import Client
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DataIntegrityError(Exception):
    """Erro de integridade de dados"""
    pass

class DataIntegrityValidator:
    """Validador de integridade de dados"""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def validate_receita_totals(
        self,
        user_id: str,
        mes: str,
        expected_total: Optional[float] = None,
        tolerance: float = 1.0
    ) -> Dict[str, any]:
        """
        Valida totais de receita para um mês específico.

        Args:
            user_id: ID do usuário
            mes: Mês no formato YYYY-MM
            expected_total: Total esperado (opcional)
            tolerance: Tolerância para diferenças

        Returns:
            Dict com resultado da validação
        """

        logger.info(f"Validando receita para {mes}, user_id={user_id}")

        # Método 1: Query direta simples
        simple_query = (
            self.supabase.table("receita_itens")
            .select("comissao_escritorio")
            .eq("user_id", user_id)
            .eq("data_ref", mes)
            .not_.ilike("familia", "%administrativo%")
        )

        simple_result = simple_query.execute()
        simple_data = simple_result.data or []
        simple_total = sum(float(item.get('comissao_escritorio', 0) or 0) for item in simple_data)

        # Método 2: Query paginada
        from data_utils.safe_pagination import safe_sum_field

        paginated_total = safe_sum_field(
            supabase=self.supabase,
            table_name="receita_itens",
            sum_field="comissao_escritorio",
            filters={
                "data_ref": mes,
                "familia": {"operator": "not_ilike", "value": "%administrativo%"}
            },
            user_id=user_id
        )

        # Comparar métodos
        method_diff = abs(simple_total - paginated_total)
        methods_match = method_diff < tolerance

        # Comparar com esperado se fornecido
        expected_match = True
        expected_diff = 0.0
        if expected_total is not None:
            expected_diff = abs(simple_total - expected_total)
            expected_match = expected_diff < tolerance

        # Resultado
        result = {
            "mes": mes,
            "user_id": user_id,
            "validation_timestamp": datetime.now().isoformat(),
            "simple_total": simple_total,
            "paginated_total": paginated_total,
            "simple_records": len(simple_data),
            "method_difference": method_diff,
            "methods_match": methods_match,
            "expected_total": expected_total,
            "expected_difference": expected_diff,
            "expected_match": expected_match,
            "overall_status": "PASS" if methods_match and expected_match else "FAIL",
            "tolerance_used": tolerance
        }

        # Log resultado
        if result["overall_status"] == "PASS":
            logger.info(f"✅ Validação PASSOU para {mes}: R$ {simple_total:,.2f}")
        else:
            logger.error(f"❌ Validação FALHOU para {mes}:")
            logger.error(f"   Simples: R$ {simple_total:,.2f}")
            logger.error(f"   Paginada: R$ {paginated_total:,.2f}")
            if expected_total:
                logger.error(f"   Esperado: R$ {expected_total:,.2f}")

        return result

    def validate_all_months(
        self,
        user_id: str,
        year: int = 2025,
        tolerance: float = 1.0
    ) -> List[Dict[str, any]]:
        """
        Valida todos os meses de um ano.

        Args:
            user_id: ID do usuário
            year: Ano a validar
            tolerance: Tolerância para diferenças

        Returns:
            Lista de resultados de validação
        """

        results = []
        months = [f"{year}-{month:02d}" for month in range(1, 13)]

        for mes in months:
            try:
                result = self.validate_receita_totals(user_id, mes, tolerance=tolerance)
                results.append(result)
            except Exception as e:
                logger.error(f"Erro validando {mes}: {e}")
                results.append({
                    "mes": mes,
                    "user_id": user_id,
                    "overall_status": "ERROR",
                    "error": str(e)
                })

        # Resumo
        passed = sum(1 for r in results if r.get("overall_status") == "PASS")
        failed = sum(1 for r in results if r.get("overall_status") == "FAIL")
        errors = sum(1 for r in results if r.get("overall_status") == "ERROR")

        logger.info(f"Validação anual {year}: ✅ {passed} | ❌ {failed} | 🚨 {errors}")

        return results

    def log_integrity_check(
        self,
        validation_results: List[Dict[str, any]],
        log_to_file: bool = True
    ):
        """
        Registra resultados de validação.

        Args:
            validation_results: Resultados da validação
            log_to_file: Se deve salvar em arquivo
        """

        if log_to_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"integrity_check_{timestamp}.json"

            try:
                import json
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(validation_results, f, indent=2, ensure_ascii=False)
                logger.info(f"Relatório salvo em: {filename}")
            except Exception as e:
                logger.error(f"Erro salvando relatório: {e}")

        # Log resumo no console
        for result in validation_results:
            status = result.get("overall_status", "UNKNOWN")
            mes = result.get("mes", "?")
            if status == "PASS":
                logger.info(f"✅ {mes}: R$ {result.get('simple_total', 0):,.2f}")
            elif status == "FAIL":
                logger.warning(f"❌ {mes}: Diff R$ {result.get('method_difference', 0):,.2f}")
            else:
                logger.error(f"🚨 {mes}: {result.get('error', 'Erro desconhecido')}")

# Exemplo de uso:
"""
from data_utils.data_integrity import DataIntegrityValidator

validator = DataIntegrityValidator(supabase)

# Validar fevereiro especificamente
result = validator.validate_receita_totals(
    user_id="49bfe132-04dc-4552-9088-99acea0f9310",
    mes="2025-02",
    expected_total=32881.30
)

# Validar ano completo
results = validator.validate_all_months(
    user_id="49bfe132-04dc-4552-9088-99acea0f9310",
    year=2025
)

# Salvar relatório
validator.log_integrity_check(results)
"""