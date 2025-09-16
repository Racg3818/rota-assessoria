#!/usr/bin/env python3
"""
Script de debug para investigar problemas no Dashboard
"""

import os
import sys
import json
from datetime import datetime

# Adicionar o diretório atual ao sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Carregar configurações
from config import Config
from dotenv import load_dotenv
load_dotenv(".env.local")

def test_supabase_connection():
    """Testa conexão básica com Supabase"""
    print("=== TESTE DE CONEXÃO SUPABASE ===")

    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    anon_key = os.getenv("SUPABASE_ANON_KEY")

    print(f"URL: {url}")
    print(f"SERVICE_KEY presente: {bool(service_key)}")
    print(f"ANON_KEY presente: {bool(anon_key)}")

    if service_key:
        print(f"SERVICE_KEY prefix: {service_key[:10]}...{service_key[-10:]}")
    if anon_key:
        print(f"ANON_KEY prefix: {anon_key[:10]}...{anon_key[-10:]}")

    try:
        from supabase import create_client
        client = create_client(url, service_key)
        print("OK Cliente Supabase criado com sucesso")

        # Teste básico de conexão
        result = client.table("clientes").select("count", count="exact").limit(1).execute()
        count = result.count or 0
        print(f"OK Teste de conexao: {count} clientes encontrados")
        return client, count

    except Exception as e:
        print(f"ERRO ao conectar Supabase: {e}")
        return None, 0

def test_user_simulation():
    """Simula sessão de usuário para testes"""
    print("\n=== SIMULAÇÃO DE USUÁRIO ===")

    # Dados de usuário simulados (baseados nos logs anteriores)
    mock_user = {
        "id": "12345678-1234-1234-1234-123456789012",  # UUID simulado
        "email": "test@svninvest.com.br",
        "nome": "Usuário Teste",
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token"
    }

    print(f"Usuário simulado: {mock_user['email']}")
    print(f"UUID simulado: {mock_user['id']}")

    return mock_user

def test_dashboard_queries(client, mock_user_id):
    """Testa queries específicas do dashboard"""
    print(f"\n=== TESTE DE QUERIES DO DASHBOARD ===")

    if not client:
        print("❌ Cliente Supabase não disponível")
        return

    # 1. Teste clientes
    try:
        result = client.table("clientes").select("*").eq("user_id", mock_user_id).limit(5).execute()
        clientes = result.data or []
        print(f"CLIENTES encontrados para user_id {mock_user_id}: {len(clientes)}")
        if clientes:
            cliente_sample = clientes[0]
            print(f"   Exemplo: {cliente_sample.get('nome', 'N/A')} (NET: {cliente_sample.get('net_total', 'N/A')})")
    except Exception as e:
        print(f"ERRO ao buscar clientes: {e}")

    # 2. Teste metas
    mes_atual = datetime.today().strftime("%Y-%m")
    try:
        result = client.table("metas_mensais").select("*").eq("user_id", mock_user_id).eq("mes", mes_atual).execute()
        metas = result.data or []
        print(f"METAS encontradas para {mes_atual}: {len(metas)}")
        if metas:
            print(f"   Meta valor: {metas[0].get('meta_receita', 'N/A')}")
    except Exception as e:
        print(f"ERRO ao buscar metas: {e}")

    # 3. Teste receitas
    try:
        result = client.table("receita_itens").select("data_ref, valor_liquido").eq("user_id", mock_user_id).limit(5).execute()
        receitas = result.data or []
        print(f"RECEITAS encontradas: {len(receitas)}")
        if receitas:
            total = sum(float(r.get('valor_liquido', 0)) for r in receitas)
            print(f"   Total dos primeiros 5: {total}")
    except Exception as e:
        print(f"ERRO ao buscar receitas: {e}")

    # 4. Teste alocações
    try:
        result = client.table("alocacoes").select("valor, efetivada").eq("user_id", mock_user_id).limit(5).execute()
        alocacoes = result.data or []
        print(f"ALOCACOES encontradas: {len(alocacoes)}")
        if alocacoes:
            efetivadas = sum(1 for a in alocacoes if a.get('efetivada'))
            print(f"   Efetivadas: {efetivadas}/{len(alocacoes)}")
    except Exception as e:
        print(f"ERRO ao buscar alocacoes: {e}")

def test_specific_user_data():
    """Testa dados de usuário específico se encontrar"""
    print(f"\n=== TESTE COM DADOS REAIS ===")

    client, total_clientes = test_supabase_connection()
    if not client:
        return

    # Buscar usuários reais na base
    try:
        result = client.table("clientes").select("user_id").limit(10).execute()
        users_found = set()
        for cliente in (result.data or []):
            user_id = cliente.get("user_id")
            if user_id:
                users_found.add(user_id)

        print(f"User IDs encontrados na base: {len(users_found)}")

        if users_found:
            # Pegar primeiro user_id real
            real_user_id = list(users_found)[0]
            print(f"Testando com user_id real: {real_user_id}")
            test_dashboard_queries(client, real_user_id)
        else:
            print("ERRO Nenhum user_id encontrado nos clientes")

    except Exception as e:
        print(f"ERRO ao buscar user_ids: {e}")

def main():
    """Função principal de debug"""
    print("DASHBOARD DEBUG SCRIPT")
    print("=" * 50)

    # Testes básicos
    client, total_clientes = test_supabase_connection()
    mock_user = test_user_simulation()

    # Testes com usuário simulado
    test_dashboard_queries(client, mock_user["id"])

    # Testes com dados reais
    test_specific_user_data()

    print("\n" + "=" * 50)
    print("DEBUG COMPLETO OK")

if __name__ == "__main__":
    main()