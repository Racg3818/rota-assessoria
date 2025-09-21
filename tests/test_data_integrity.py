# tests/test_data_integrity.py
"""
🧪 TESTES AUTOMATIZADOS PARA INTEGRIDADE DE DADOS
Garante que correções funcionem e detecta regressões.
"""

import unittest
from unittest.mock import Mock, patch
import sys
import os

# Adicionar diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestDataIntegrity(unittest.TestCase):
    """Testes de integridade de dados"""

    def setUp(self):
        """Setup para cada teste"""
        self.mock_supabase = Mock()
        self.test_user_id = "49bfe132-04dc-4552-9088-99acea0f9310"

    def test_receita_fevereiro_consistency(self):
        """Testa consistência da receita de fevereiro"""

        # Mock dos dados de retorno
        mock_data = [
            {"comissao_escritorio": 1000.0},
            {"comissao_escritorio": 2000.0},
            {"comissao_escritorio": 500.0}
        ]

        # Configurar mock para retornar dados consistentes
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.not_.ilike.return_value.execute.return_value.data = mock_data

        from data_utils.data_integrity import DataIntegrityValidator

        validator = DataIntegrityValidator(self.mock_supabase)

        # Mock da função de paginação segura
        with patch('data_utils.safe_pagination.safe_sum_field', return_value=3500.0):
            result = validator.validate_receita_totals(
                user_id=self.test_user_id,
                mes="2025-02",
                expected_total=3500.0
            )

        # Verificações
        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["simple_total"], 3500.0)
        self.assertTrue(result["methods_match"])
        self.assertTrue(result["expected_match"])

    def test_receita_inconsistency_detection(self):
        """Testa detecção de inconsistências"""

        # Mock dados inconsistentes
        mock_data = [{"comissao_escritorio": 1000.0}]

        self.mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.not_.ilike.return_value.execute.return_value.data = mock_data

        from data_utils.data_integrity import DataIntegrityValidator

        validator = DataIntegrityValidator(self.mock_supabase)

        # Mock paginação retornando valor diferente
        with patch('data_utils.safe_pagination.safe_sum_field', return_value=2000.0):
            result = validator.validate_receita_totals(
                user_id=self.test_user_id,
                mes="2025-02",
                expected_total=1000.0
            )

        # Deve detectar inconsistência entre métodos
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertEqual(result["simple_total"], 1000.0)
        self.assertEqual(result["paginated_total"], 2000.0)
        self.assertFalse(result["methods_match"])

    def test_safe_pagination_basic(self):
        """Testa paginação segura básica"""

        from data_utils.safe_pagination import safe_paginated_query

        # Mock de múltiplas páginas
        page1_data = [{"id": 1, "valor": 100}, {"id": 2, "valor": 200}]
        page2_data = [{"id": 3, "valor": 300}]
        page3_data = []  # Página vazia (fim)

        mock_responses = [
            Mock(data=page1_data),
            Mock(data=page2_data),
            Mock(data=page3_data)
        ]

        self.mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.side_effect = mock_responses

        result = safe_paginated_query(
            supabase=self.mock_supabase,
            table_name="test_table",
            select_fields="id, valor",
            user_id=self.test_user_id,
            page_size=2
        )

        # Deve retornar todos os registros de todas as páginas
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["id"], 1)
        self.assertEqual(result[2]["id"], 3)

    def test_monitoring_alerts(self):
        """Testa sistema de alertas"""

        from data_utils.monitoring import ReceiptaMonitor

        alerts_received = []

        def custom_alert_handler(alert):
            alerts_received.append(alert)

        monitor = ReceiptaMonitor(self.mock_supabase, custom_alert_handler)

        # Adicionar alertas de diferentes severidades
        monitor.add_alert("INFO", "TEST", "Teste info", {"key": "value"})
        monitor.add_alert("ERROR", "TEST", "Teste erro", {"error": "test"})

        # Verificar alertas
        self.assertEqual(len(alerts_received), 2)
        self.assertEqual(alerts_received[0].severity, "INFO")
        self.assertEqual(alerts_received[1].severity, "ERROR")

        # Testar filtros
        error_alerts = monitor.get_alerts(severity="ERROR")
        self.assertEqual(len(error_alerts), 1)
        self.assertEqual(error_alerts[0].severity, "ERROR")

    def test_health_report_generation(self):
        """Testa geração de relatório de saúde"""

        from data_utils.monitoring import ReceiptaMonitor

        monitor = ReceiptaMonitor(self.mock_supabase)

        # Adicionar alguns alertas
        monitor.add_alert("INFO", "TEST", "Info message")
        monitor.add_alert("ERROR", "TEST", "Error message")
        monitor.add_alert("CRITICAL", "TEST", "Critical message")

        # Gerar relatório
        health = monitor.generate_health_report()

        # Verificações
        self.assertIn("overall_status", health)
        self.assertIn("total_alerts", health)
        self.assertIn("severity_breakdown", health)
        self.assertIn("recommendations", health)

        # Com alerta crítico, status deve ser CRITICAL
        self.assertEqual(health["overall_status"], "CRITICAL")
        self.assertEqual(health["total_alerts"], 3)

class TestReceitaCalculation(unittest.TestCase):
    """Testes específicos para cálculo de receita"""

    def test_extract_digits_function(self):
        """Testa função de extração de dígitos"""

        # Import da função real
        sys.path.insert(0, 'views')
        try:
            from receita import _extract_digits

            # Testes
            self.assertEqual(_extract_digits("ABC123DEF"), "123")
            self.assertEqual(_extract_digits("12345"), "12345")
            self.assertEqual(_extract_digits(""), "")
            self.assertEqual(_extract_digits(None), "")
            self.assertEqual(_extract_digits("ABC"), "")

            # Teste com múltiplos números (deve retornar o maior)
            self.assertEqual(_extract_digits("123-45678-90"), "45678")

        except ImportError:
            self.skipTest("Módulo receita não disponível para teste")

    def test_to_float_function(self):
        """Testa função de conversão para float"""

        sys.path.insert(0, 'views')
        try:
            from receita import _to_float

            # Testes
            self.assertEqual(_to_float(123), 123.0)
            self.assertEqual(_to_float("123.45"), 123.45)
            self.assertEqual(_to_float("1.234,56"), 1234.56)  # Formato brasileiro
            self.assertEqual(_to_float(None), 0.0)
            self.assertEqual(_to_float(""), 0.0)
            self.assertEqual(_to_float("NULL"), 0.0)

        except ImportError:
            self.skipTest("Módulo receita não disponível para teste")

# Test runner personalizado
def run_integrity_tests():
    """Executa todos os testes de integridade"""

    # Configurar logging para testes
    import logging
    logging.basicConfig(level=logging.INFO)

    # Criar suite de testes
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Adicionar testes
    suite.addTests(loader.loadTestsFromTestCase(TestDataIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestReceitaCalculation))

    # Executar testes
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Relatório
    print(f"\n{'='*50}")
    print(f"RESULTADO DOS TESTES:")
    print(f"{'='*50}")
    print(f"Testes executados: {result.testsRun}")
    print(f"Falhas: {len(result.failures)}")
    print(f"Erros: {len(result.errors)}")

    if result.failures:
        print(f"\nFALHAS:")
        for test, trace in result.failures:
            print(f"- {test}: {trace}")

    if result.errors:
        print(f"\nERROS:")
        for test, trace in result.errors:
            print(f"- {test}: {trace}")

    success = len(result.failures) == 0 and len(result.errors) == 0
    print(f"\nSTATUS: {'PASSOU' if success else 'FALHOU'}")

    return success

if __name__ == "__main__":
    run_integrity_tests()