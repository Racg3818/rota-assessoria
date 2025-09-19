#!/usr/bin/env python3
"""
🚨 SCRIPT DE AUDITORIA DE SEGURANÇA
Detecta possíveis vazamentos de dados entre usuários.
Execute regularmente para monitorar a segurança do sistema.
"""

import os
import sys
import re
from datetime import datetime
from typing import Dict, List, Set

# Adicionar diretório atual ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class SecurityAudit:
    def __init__(self):
        self.vulnerabilities = []
        self.warnings = []
        self.info = []

    def log_vulnerability(self, file_path: str, line: int, issue: str, details: str = ""):
        """Registra uma vulnerabilidade crítica."""
        self.vulnerabilities.append({
            'file': file_path,
            'line': line,
            'issue': issue,
            'details': details,
            'severity': 'HIGH'
        })

    def log_warning(self, file_path: str, line: int, issue: str, details: str = ""):
        """Registra um aviso de segurança."""
        self.warnings.append({
            'file': file_path,
            'line': line,
            'issue': issue,
            'details': details,
            'severity': 'MEDIUM'
        })

    def log_info(self, message: str):
        """Registra informação geral."""
        self.info.append(message)

    def scan_file(self, file_path: str):
        """Escaneia um arquivo Python em busca de vulnerabilidades."""
        if not file_path.endswith('.py'):
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            self.log_warning(file_path, 0, f"Erro ao ler arquivo: {e}")
            return

        for line_num, line in enumerate(lines, 1):
            line_clean = line.strip()

            # 🚨 VULNERABILIDADE CRÍTICA: Cliente admin sem filtro user_id
            if 'supabase_admin.table(' in line and '.eq("user_id"' not in line:
                self.log_vulnerability(
                    file_path, line_num,
                    "Cliente admin sem filtro user_id",
                    f"Linha: {line_clean}"
                )

            # 🚨 VULNERABILIDADE CRÍTICA: list_users() que pode expor dados
            if 'list_users()' in line or 'admin.list_users()' in line:
                self.log_vulnerability(
                    file_path, line_num,
                    "list_users() pode expor dados de todos os usuários",
                    f"Linha: {line_clean}"
                )

            # 🚨 VULNERABILIDADE CRÍTICA: SELECT sem WHERE user_id
            if re.search(r'\.select\(.*\)\.execute\(\)', line) and 'eq("user_id"' not in line:
                # Verificar se não há filtro user_id na linha seguinte
                next_line = lines[line_num] if line_num < len(lines) else ""
                if 'eq("user_id"' not in next_line:
                    self.log_vulnerability(
                        file_path, line_num,
                        "Query SELECT sem filtro user_id",
                        f"Linha: {line_clean}"
                    )

            # ⚠️ AVISO: Cliente admin sendo usado
            if 'supabase_admin' in line and 'import' not in line:
                self.log_warning(
                    file_path, line_num,
                    "Uso de cliente admin detectado",
                    f"Linha: {line_clean}"
                )

            # ⚠️ AVISO: get_supabase_client() sem verificação de None
            if 'get_supabase_client()' in line and 'if' not in line and '=' in line:
                self.log_warning(
                    file_path, line_num,
                    "get_supabase_client() sem verificação de None",
                    f"Linha: {line_clean}"
                )

            # BOA PRÁTICA: Filtro user_id encontrado
            if '.eq("user_id"' in line:
                self.log_info(f"OK - Filtro user_id encontrado em {file_path}:{line_num}")

    def scan_directory(self, directory: str):
        """Escaneia todos os arquivos Python em um diretório."""
        for root, dirs, files in os.walk(directory):
            # Ignorar diretórios de cache e temporários
            dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', 'venv', 'env']]

            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    self.scan_file(file_path)

    def generate_report(self) -> str:
        """Gera relatório de auditoria de segurança."""
        report = []
        report.append("RELATORIO DE AUDITORIA DE SEGURANCA")
        report.append("=" * 50)
        report.append(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        if self.vulnerabilities:
            report.append(f"VULNERABILIDADES CRITICAS ({len(self.vulnerabilities)}):")
            report.append("-" * 40)
            for vuln in self.vulnerabilities:
                report.append(f"ARQUIVO: {vuln['file']}:{vuln['line']}")
                report.append(f"PROBLEMA: {vuln['issue']}")
                report.append(f"DETALHES: {vuln['details']}")
                report.append("")
        else:
            report.append("OK - NENHUMA VULNERABILIDADE CRITICA ENCONTRADA")
            report.append("")

        if self.warnings:
            report.append(f"AVISOS DE SEGURANCA ({len(self.warnings)}):")
            report.append("-" * 40)
            for warn in self.warnings:
                report.append(f"ARQUIVO: {warn['file']}:{warn['line']}")
                report.append(f"AVISO: {warn['issue']}")
                report.append(f"DETALHES: {warn['details']}")
                report.append("")
        else:
            report.append("OK - NENHUM AVISO DE SEGURANCA")
            report.append("")

        # Resumo
        report.append("RESUMO:")
        report.append(f"- Vulnerabilidades criticas: {len(self.vulnerabilities)}")
        report.append(f"- Avisos de seguranca: {len(self.warnings)}")
        report.append(f"- Filtros user_id encontrados: {len([i for i in self.info if 'user_id' in i])}")

        return "\\n".join(report)

def main():
    """Executa auditoria de segurança."""
    audit = SecurityAudit()

    # Escanear diretório atual
    current_dir = os.path.dirname(os.path.abspath(__file__))
    audit.scan_directory(current_dir)

    # Gerar e exibir relatório
    report = audit.generate_report()
    print(report)

    # Salvar relatório em arquivo
    report_file = os.path.join(current_dir, f"security_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\\nRelatório salvo em: {report_file}")

    # Status de saída
    if audit.vulnerabilities:
        print("\\nFALHOU - Vulnerabilidades criticas encontradas!")
        sys.exit(1)
    elif audit.warnings:
        print("\\nCOM AVISOS - Revisar avisos de seguranca")
        sys.exit(2)
    else:
        print("\\nPASSOI - Sistema seguro")
        sys.exit(0)

if __name__ == "__main__":
    main()