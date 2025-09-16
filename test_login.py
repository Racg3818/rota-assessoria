#!/usr/bin/env python3
"""
Testa login e acesso ao dashboard para debug
"""

import requests
import sys
from datetime import datetime

# Configuração
BASE_URL = "http://127.0.0.1:3001"

def test_login():
    """Testa fluxo de login"""
    print("=== TESTE DE LOGIN ===")

    session = requests.Session()

    # 1. Pegar a página de login para verificar se está funcionando
    try:
        resp = session.get(f"{BASE_URL}/login")
        print(f"GET /login: {resp.status_code}")
        if resp.status_code != 200:
            print(f"Erro ao acessar login: {resp.text}")
            return None
    except Exception as e:
        print(f"Erro ao conectar: {e}")
        return None

    # 2. Fazer login com dados de teste
    login_data = {
        'nome': 'Usuario Teste',
        'email': 'test@svninvest.com.br',
        'codigo_xp': '12345',
        'senha': ''  # senha opcional para não-admin
    }

    try:
        resp = session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=False)
        print(f"POST /login: {resp.status_code}")

        if resp.status_code == 302:
            print("Login redirecionado com sucesso")
            return session
        else:
            print(f"Erro no login: {resp.text}")
            return None
    except Exception as e:
        print(f"Erro ao fazer login: {e}")
        return None

def test_dashboard(session):
    """Testa acesso ao dashboard"""
    print("\n=== TESTE DO DASHBOARD ===")

    if not session:
        print("Sessão inválida")
        return

    try:
        resp = session.get(f"{BASE_URL}/dashboard/")
        print(f"GET /dashboard/: {resp.status_code}")

        if resp.status_code == 200:
            # Verificar se tem dados no HTML
            html = resp.text

            # Buscar por indicadores de dados carregados
            indicators = [
                "receita_total",
                "meta_receita",
                "mediana_net",
                "penetracao_pct",
                "clientes"
            ]

            found_data = {}
            for indicator in indicators:
                if indicator in html:
                    # Tentar extrair valor básico
                    import re
                    pattern = f'{indicator}["\']?\\s*[:=]\\s*([\\d.,]+)'
                    match = re.search(pattern, html)
                    if match:
                        found_data[indicator] = match.group(1)
                    else:
                        found_data[indicator] = "encontrado na página"
                else:
                    found_data[indicator] = "NÃO ENCONTRADO"

            print("Dados encontrados na página:")
            for key, value in found_data.items():
                print(f"  {key}: {value}")

            # Verificar se há mensagens de erro
            if "Nenhum" in html or "vazio" in html.lower() or "error" in html.lower():
                print("AVISO: Possíveis indicadores de dados vazios na página")

        else:
            print(f"Erro ao acessar dashboard: {resp.text}")

    except Exception as e:
        print(f"Erro ao testar dashboard: {e}")

def test_debug_endpoint(session):
    """Testa endpoint de debug"""
    print("\n=== TESTE DO DEBUG ENDPOINT ===")

    if not session:
        print("Sessão inválida")
        return

    try:
        resp = session.get(f"{BASE_URL}/dashboard/debug")
        print(f"GET /dashboard/debug: {resp.status_code}")

        if resp.status_code == 200:
            print("Resposta debug:")
            print(resp.text[:1000] + "..." if len(resp.text) > 1000 else resp.text)
        else:
            print(f"Erro no debug: {resp.text}")

    except Exception as e:
        print(f"Erro ao testar debug: {e}")

def main():
    print("TESTE DE LOGIN E DASHBOARD")
    print("=" * 50)

    # Login
    session = test_login()

    # Dashboard
    test_dashboard(session)

    # Debug endpoint
    test_debug_endpoint(session)

    print("\n" + "=" * 50)
    print("TESTE COMPLETO")

if __name__ == "__main__":
    main()