#!/usr/bin/env python3
"""
Teste direto do dashboard com logs detalhados
"""

import requests
import time

def test_dashboard_with_details():
    """Teste mais detalhado do dashboard"""
    print("=== TESTE DIRETO DO DASHBOARD ===")

    session = requests.Session()

    # 1. Login
    print("1. Fazendo login...")
    login_data = {
        'nome': 'Usuario Teste',
        'email': 'test@svninvest.com.br',
        'codigo_xp': '12345',
        'senha': ''
    }

    resp = session.post("http://127.0.0.1:3001/login", data=login_data, allow_redirects=False)
    if resp.status_code != 302:
        print(f"Erro no login: {resp.status_code}")
        return

    print("Login OK")

    # 2. Aguardar um pouco para logs
    time.sleep(1)

    # 3. Acessar dashboard
    print("2. Acessando dashboard...")
    resp = session.get("http://127.0.0.1:3001/dashboard/")

    if resp.status_code != 200:
        print(f"Erro ao acessar dashboard: {resp.status_code}")
        return

    html = resp.text

    # 4. Buscar dados específicos no HTML
    print("3. Analisando HTML do dashboard...")

    # Buscar por indicadores de valores
    import re

    # Buscar receita total
    receita_match = re.search(r'receita[_-]?total["\']?\s*[:=]\s*([0-9.,]+)', html, re.IGNORECASE)
    if receita_match:
        print(f"   Receita total encontrada: {receita_match.group(1)}")
    else:
        print("   Receita total: NÃO ENCONTRADA")

    # Buscar meta
    meta_match = re.search(r'meta[_-]?receita["\']?\s*[:=]\s*([0-9.,]+)', html, re.IGNORECASE)
    if meta_match:
        print(f"   Meta encontrada: {meta_match.group(1)}")
    else:
        print("   Meta: NÃO ENCONTRADA")

    # Buscar mediana NET
    mediana_match = re.search(r'mediana[_-]?net["\']?\s*[:=]\s*([0-9.,]+)', html, re.IGNORECASE)
    if mediana_match:
        print(f"   Mediana NET encontrada: {mediana_match.group(1)}")
    else:
        print("   Mediana NET: NÃO ENCONTRADA")

    # Buscar por qualquer número grande (indicador de dados carregados)
    big_numbers = re.findall(r'\b([0-9]{4,}(?:\.[0-9]+)?)\b', html)
    if big_numbers:
        print(f"   Números grandes encontrados: {big_numbers[:5]}")
    else:
        print("   Nenhum número grande encontrado")

    # Verificar se há tabelas ou listas
    if '<table' in html.lower():
        print("   Tabelas encontradas na página")
    if '<li' in html.lower():
        print("   Listas encontradas na página")

    # Buscar por mensagens de erro ou vazio
    error_indicators = ['nenhum', 'vazio', 'erro', 'error', '0,00', 'R$ 0']
    found_errors = []
    for indicator in error_indicators:
        if indicator.lower() in html.lower():
            found_errors.append(indicator)

    if found_errors:
        print(f"   Possíveis indicadores de dados vazios: {found_errors}")

    # Salvar HTML para análise manual
    with open('dashboard_output.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("   HTML salvo em dashboard_output.html para análise manual")

if __name__ == "__main__":
    test_dashboard_with_details()