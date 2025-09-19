#!/usr/bin/env python3
"""
Script de teste para a migração do sistema de autenticação
Executa testes pré e pós migração para garantir que tudo funciona
"""

import os
import sys
from dotenv import load_dotenv, find_dotenv

# Carregar ambiente
load_dotenv(find_dotenv(".env.local", usecwd=True))
load_dotenv()

def test_supabase_connection():
    """Testa conexão básica com Supabase"""
    print("Testando conexao com Supabase...")

    try:
        from supabase import create_client

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

        if not url or not key:
            print("Variaveis de ambiente nao configuradas")
            return False

        client = create_client(url, key)

        # Teste básico
        result = client.table('produtos').select('count', count='exact').execute()
        count = result.count if hasattr(result, 'count') else 0

        print(f"Conexao OK - {count} produtos encontrados")
        return True

    except Exception as e:
        print(f"Erro de conexao: {e}")
        return False

def test_existing_tables():
    """Verifica tabelas existentes"""
    print("\nVerificando tabelas existentes...")

    try:
        from supabase import create_client

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        client = create_client(url, key)

        expected_tables = [
            'alocacoes', 'bonus_missoes', 'clientes',
            'metas_escritorio_classe', 'metas_mensais',
            'produtos', 'receita_itens', 'user_prefs'
        ]

        working_tables = []

        for table in expected_tables:
            try:
                result = client.table(table).select('count', count='exact').execute()
                count = result.count if hasattr(result, 'count') else 0
                print(f"OK {table}: {count} registros")
                working_tables.append(table)
            except Exception as e:
                print(f"ERRO {table}: {e}")

        return working_tables

    except Exception as e:
        print(f"Erro geral: {e}")
        return []

def test_profiles_table():
    """Verifica se tabela profiles existe e funciona"""
    print("\nTestando tabela profiles...")

    try:
        from supabase import create_client

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        client = create_client(url, key)

        # Testar se tabela existe
        result = client.table('profiles').select('count', count='exact').execute()
        count = result.count if hasattr(result, 'count') else 0

        print(f"Tabela profiles: {count} registros")

        # Testar estrutura
        if count > 0:
            sample = client.table('profiles').select('*').limit(1).execute()
            if sample.data:
                fields = list(sample.data[0].keys())
                print(f"Campos disponiveis: {', '.join(fields)}")

        return True

    except Exception as e:
        print(f"Tabela profiles ERRO: {e}")
        return False

def test_auth_users_access():
    """Verifica se conseguimos acessar dados de auth.users"""
    print("\nTestando acesso a auth.users...")

    try:
        from supabase import create_client

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        client = create_client(url, key)

        # Tentar listar usuários via API Admin
        users_list = client.auth.admin.list_users()

        if hasattr(users_list, 'users') and users_list.users:
            count = len(users_list.users)
            print(f"Auth.users via Admin API: {count} usuarios")

            # Mostrar exemplo de usuário
            if count > 0:
                user = users_list.users[0]
                print(f"   Exemplo - ID: {user.id}, Email: {user.email}")

            return True
        else:
            print("Nenhum usuario encontrado via Admin API")
            return False

    except Exception as e:
        print(f"Erro ao acessar auth.users: {e}")
        return False

def run_pre_migration_tests():
    """Executa testes antes da migração"""
    print("=" * 50)
    print("TESTES PRE-MIGRACAO")
    print("=" * 50)

    results = {}
    results['connection'] = test_supabase_connection()
    results['tables'] = len(test_existing_tables()) >= 6  # Pelo menos 6 tabelas
    results['profiles'] = test_profiles_table()
    results['auth_users'] = test_auth_users_access()

    print("\nRESUMO PRE-MIGRACAO:")
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"   {test}: {status}")

    all_passed = all(results.values())
    print(f"\nStatus geral: {'PRONTO PARA MIGRACAO' if all_passed else 'CORRIGIR PROBLEMAS ANTES'}")

    return all_passed

def run_post_migration_tests():
    """Executa testes após a migração"""
    print("=" * 50)
    print("TESTES POS-MIGRACAO")
    print("=" * 50)

    # Todos os testes pré-migração + verificações adicionais
    results = {}
    results['connection'] = test_supabase_connection()
    results['tables'] = len(test_existing_tables()) >= 6
    results['profiles'] = test_profiles_table()
    results['auth_users'] = test_auth_users_access()

    # Teste adicional: verificar sincronização
    print("\nTestando sincronizacao auth.users <-> profiles...")
    try:
        from supabase import create_client

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        client = create_client(url, key)

        # Contar usuários em auth.users
        auth_users = client.auth.admin.list_users()
        auth_count = len(auth_users.users) if hasattr(auth_users, 'users') else 0

        # Contar profiles
        profiles_result = client.table('profiles').select('count', count='exact').execute()
        profiles_count = profiles_result.count if hasattr(profiles_result, 'count') else 0

        print(f"   Auth.users: {auth_count} usuários")
        print(f"   Profiles: {profiles_count} registros")

        sync_ok = abs(auth_count - profiles_count) <= 1  # Permite diferença de 1
        results['sync'] = sync_ok

        if sync_ok:
            print("Sincronizacao OK")
        else:
            print("Dessincronia detectada")

    except Exception as e:
        print(f"Erro ao verificar sincronizacao: {e}")
        results['sync'] = False

    print("\nRESUMO POS-MIGRACAO:")
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"   {test}: {status}")

    all_passed = all(results.values())
    print(f"\nStatus geral: {'MIGRACAO CONCLUIDA' if all_passed else 'PROBLEMAS DETECTADOS'}")

    return all_passed

def main():
    """Função principal"""
    if len(sys.argv) > 1:
        if sys.argv[1] == "pre":
            return run_pre_migration_tests()
        elif sys.argv[1] == "post":
            return run_post_migration_tests()

    print("Uso:")
    print("  python test_migration.py pre   - Testes pré-migração")
    print("  python test_migration.py post  - Testes pós-migração")

    return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)