# utils/monitoring.py
"""
📊 SISTEMA DE MONITORAMENTO DE DISCREPÂNCIAS
Monitora automaticamente cálculos críticos e alerta sobre problemas.
"""

from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import threading
import time

logger = logging.getLogger(__name__)

@dataclass
class MonitoringAlert:
    """Alerta de monitoramento"""
    timestamp: datetime
    severity: str  # INFO, WARNING, ERROR, CRITICAL
    component: str
    message: str
    details: Dict
    user_id: Optional[str] = None

class ReceiptaMonitor:
    """Monitor de receitas e cálculos críticos"""

    def __init__(self, supabase, alert_callback: Optional[Callable] = None):
        self.supabase = supabase
        self.alert_callback = alert_callback or self._default_alert_handler
        self.alerts = []
        self.monitoring_active = False
        self.monitor_thread = None

    def _default_alert_handler(self, alert: MonitoringAlert):
        """Handler padrão para alertas"""
        level_map = {
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }

        level = level_map.get(alert.severity, logging.INFO)
        logger.log(level, f"[{alert.component}] {alert.message}")

        if alert.details:
            logger.log(level, f"Detalhes: {alert.details}")

    def add_alert(self, severity: str, component: str, message: str, details: Dict = None, user_id: str = None):
        """Adiciona um alerta"""
        alert = MonitoringAlert(
            timestamp=datetime.now(),
            severity=severity,
            component=component,
            message=message,
            details=details or {},
            user_id=user_id
        )

        self.alerts.append(alert)
        self.alert_callback(alert)

    def check_receita_consistency(self, user_id: str, mes: str) -> bool:
        """
        Verifica consistência de receita para um mês.

        Returns:
            True se consistente, False caso contrário
        """

        try:
            from data_utils.data_integrity import DataIntegrityValidator

            validator = DataIntegrityValidator(self.supabase)
            result = validator.validate_receita_totals(user_id, mes)

            if result["overall_status"] == "PASS":
                self.add_alert(
                    "INFO",
                    "RECEITA_CHECK",
                    f"Receita consistente para {mes}",
                    {"total": result["simple_total"], "mes": mes},
                    user_id
                )
                return True
            else:
                self.add_alert(
                    "ERROR",
                    "RECEITA_CHECK",
                    f"Inconsistência detectada em {mes}",
                    {
                        "mes": mes,
                        "simple_total": result["simple_total"],
                        "paginated_total": result["paginated_total"],
                        "difference": result["method_difference"]
                    },
                    user_id
                )
                return False

        except Exception as e:
            self.add_alert(
                "CRITICAL",
                "RECEITA_CHECK",
                f"Erro ao verificar receita de {mes}: {e}",
                {"error": str(e), "mes": mes},
                user_id
            )
            return False

    def check_pagination_patterns(self) -> List[str]:
        """
        Verifica padrões de paginação problemáticos no código.

        Returns:
            Lista de arquivos com padrões problemáticos
        """

        import os
        import re

        problematic_files = []

        # Padrões problemáticos
        patterns = [
            r'order\("data_ref"\).*range\(',  # Ordenação por data_ref com range
            r'range\(\d+,\s*\d+\)',          # Range com números hardcoded grandes
        ]

        # Arquivos para verificar
        files_to_check = [
            "views/receita.py",
            "views/dashboard.py",
            "views/finadvisor.py",
            "views/alocacoes.py",
            "views/clientes.py"
        ]

        for file_path in files_to_check:
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    for pattern in patterns:
                        if re.search(pattern, content):
                            problematic_files.append(file_path)
                            self.add_alert(
                                "WARNING",
                                "CODE_PATTERN",
                                f"Padrão problemático encontrado em {file_path}",
                                {"pattern": pattern, "file": file_path}
                            )
                            break

                except Exception as e:
                    self.add_alert(
                        "ERROR",
                        "CODE_PATTERN",
                        f"Erro ao verificar {file_path}: {e}",
                        {"file": file_path, "error": str(e)}
                    )

        return problematic_files

    def monitor_critical_calculations(self, user_ids: List[str], interval_minutes: int = 60):
        """
        Monitora cálculos críticos periodicamente.

        Args:
            user_ids: Lista de user_ids para monitorar
            interval_minutes: Intervalo entre verificações
        """

        def monitor_loop():
            while self.monitoring_active:
                try:
                    # Verificar mês atual e anterior
                    now = datetime.now()
                    current_month = now.strftime("%Y-%m")

                    # Mês anterior
                    prev_month_date = now.replace(day=1) - timedelta(days=1)
                    prev_month = prev_month_date.strftime("%Y-%m")

                    for user_id in user_ids:
                        # Verificar mês atual
                        self.check_receita_consistency(user_id, current_month)

                        # Verificar mês anterior (dados mais estáveis)
                        self.check_receita_consistency(user_id, prev_month)

                    # Verificar padrões de código
                    self.check_pagination_patterns()

                    # Aguardar próxima verificação
                    time.sleep(interval_minutes * 60)

                except Exception as e:
                    self.add_alert(
                        "ERROR",
                        "MONITOR_LOOP",
                        f"Erro no loop de monitoramento: {e}",
                        {"error": str(e)}
                    )
                    time.sleep(300)  # 5 minutos em caso de erro

        self.monitoring_active = True
        self.monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitor_thread.start()

        self.add_alert(
            "INFO",
            "MONITOR",
            f"Monitoramento iniciado para {len(user_ids)} usuários",
            {"interval_minutes": interval_minutes, "user_count": len(user_ids)}
        )

    def stop_monitoring(self):
        """Para o monitoramento"""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)

        self.add_alert("INFO", "MONITOR", "Monitoramento interrompido", {})

    def get_alerts(self, severity: Optional[str] = None, component: Optional[str] = None, limit: int = 100) -> List[MonitoringAlert]:
        """
        Obtém alertas filtrados.

        Args:
            severity: Filtrar por severidade
            component: Filtrar por componente
            limit: Limite de alertas

        Returns:
            Lista de alertas
        """

        filtered = self.alerts

        if severity:
            filtered = [a for a in filtered if a.severity == severity]

        if component:
            filtered = [a for a in filtered if a.component == component]

        # Ordenar por timestamp (mais recente primeiro)
        filtered.sort(key=lambda x: x.timestamp, reverse=True)

        return filtered[:limit]

    def generate_health_report(self) -> Dict:
        """
        Gera relatório de saúde do sistema.

        Returns:
            Relatório com métricas de saúde
        """

        now = datetime.now()
        last_24h = now - timedelta(hours=24)

        recent_alerts = [a for a in self.alerts if a.timestamp >= last_24h]

        severity_counts = {}
        component_counts = {}

        for alert in recent_alerts:
            severity_counts[alert.severity] = severity_counts.get(alert.severity, 0) + 1
            component_counts[alert.component] = component_counts.get(alert.component, 0) + 1

        # Status geral
        critical_count = severity_counts.get("CRITICAL", 0)
        error_count = severity_counts.get("ERROR", 0)

        if critical_count > 0:
            overall_status = "CRITICAL"
        elif error_count > 5:  # Mais de 5 erros em 24h
            overall_status = "DEGRADED"
        elif error_count > 0:
            overall_status = "WARNING"
        else:
            overall_status = "HEALTHY"

        return {
            "timestamp": now.isoformat(),
            "overall_status": overall_status,
            "monitoring_active": self.monitoring_active,
            "total_alerts": len(self.alerts),
            "alerts_24h": len(recent_alerts),
            "severity_breakdown": severity_counts,
            "component_breakdown": component_counts,
            "recommendations": self._generate_recommendations(recent_alerts)
        }

    def _generate_recommendations(self, recent_alerts: List[MonitoringAlert]) -> List[str]:
        """Gera recomendações baseadas em alertas recentes"""

        recommendations = []

        # Verificar padrões
        receita_errors = [a for a in recent_alerts if a.component == "RECEITA_CHECK" and a.severity in ["ERROR", "CRITICAL"]]
        code_warnings = [a for a in recent_alerts if a.component == "CODE_PATTERN"]

        if receita_errors:
            recommendations.append("⚠️ Detectadas inconsistências em cálculos de receita - revisar paginação")

        if code_warnings:
            recommendations.append("🔍 Padrões problemáticos no código - considerar refatoração")

        if len(recent_alerts) > 20:
            recommendations.append("📊 Alto volume de alertas - investigar causa raiz")

        if not recommendations:
            recommendations.append("✅ Sistema funcionando normalmente")

        return recommendations

# Exemplo de uso:
"""
from data_utils.monitoring import ReceiptaMonitor

# Inicializar monitor
monitor = ReceiptaMonitor(supabase)

# Verificação pontual
monitor.check_receita_consistency("49bfe132-04dc-4552-9088-99acea0f9310", "2025-02")

# Monitoramento contínuo
monitor.monitor_critical_calculations(["49bfe132-04dc-4552-9088-99acea0f9310"], interval_minutes=30)

# Relatório de saúde
health = monitor.generate_health_report()
print(health)

# Parar monitoramento
monitor.stop_monitoring()
"""