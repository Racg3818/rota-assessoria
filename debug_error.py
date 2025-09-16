#!/usr/bin/env python3
"""
Script de diagnóstico para identificar erros específicos no sistema.
"""
import os
import sys
import traceback
from flask import Flask

def test_imports():
    """Testa imports individuais para identificar problemas."""
    print("=== TESTE DE IMPORTS ===")

    modules_to_test = [
        'cache_manager',
        'views.auth',
        'views.dashboard',
        'views.receita',
        'views.clientes',
        'views.alocacoes',
        'views.finadvisor',
        'views.importar'
    ]

    for module in modules_to_test:
        try:
            __import__(module)
            print(f"OK {module}")
        except Exception as e:
            print(f"ERRO {module}: {e}")
            traceback.print_exc()
            print("-" * 50)

def test_app_creation():
    """Testa criação da aplicação."""
    print("\n=== TESTE DE CRIAÇÃO DO APP ===")
    try:
        from app import create_app
        app = create_app()
        print("OK App criado com sucesso")
        return app
    except Exception as e:
        print(f"ERRO ao criar app: {e}")
        traceback.print_exc()
        return None

def test_routes_registration(app):
    """Testa se as rotas estão registradas corretamente."""
    print("\n=== TESTE DE ROTAS ===")
    if not app:
        print("ERRO App nao disponivel")
        return

    try:
        with app.app_context():
            for rule in app.url_map.iter_rules():
                print(f"OK Rota: {rule.rule} -> {rule.endpoint}")
    except Exception as e:
        print(f"ERRO ao listar rotas: {e}")
        traceback.print_exc()

def test_supabase_references():
    """Verifica referências problemáticas ao supabase."""
    print("\n=== VERIFICANDO REFERÊNCIAS SUPABASE ===")

    import ast
    import glob

    for file_path in glob.glob("views/*.py"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Procurar por 'if supabase:' sem definição prévia
            lines = content.split('\n')
            in_function = False
            function_name = ""
            has_supabase_def = False

            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # Detecta início de função
                if stripped.startswith('def '):
                    in_function = True
                    function_name = stripped.split('(')[0].replace('def ', '')
                    has_supabase_def = False

                # Detecta fim da função (nova função ou linha não indentada)
                elif in_function and line and not line.startswith((' ', '\t')):
                    in_function = False

                # Verifica definição de supabase
                if in_function and ('supabase = ' in stripped or '_get_supabase()' in stripped):
                    has_supabase_def = True

                # Verifica uso de supabase sem definição
                if (in_function and
                    ('if supabase:' in stripped or 'if not supabase:' in stripped or 'supabase.' in stripped) and
                    not has_supabase_def and
                    'get_supabase_client' not in stripped):
                    print(f"AVISO {file_path}:{i} - Funcao '{function_name}' usa 'supabase' sem definicao")
                    print(f"    Linha: {stripped}")

        except Exception as e:
            print(f"ERRO ao analisar {file_path}: {e}")

def test_cache_manager():
    """Testa o cache manager especificamente."""
    print("\n=== TESTE DO CACHE MANAGER ===")
    try:
        from cache_manager import cached_by_user, get_user_id, init_cache

        # Testar fora de contexto
        uid = get_user_id()
        print(f"OK get_user_id() fora de contexto: {uid}")

        # Testar criação de app com cache
        app = Flask(__name__)
        cache = init_cache(app)
        print(f"OK Cache inicializado: {type(cache)}")

    except Exception as e:
        print(f"ERRO no cache manager: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    print("DIAGNOSTICO DO SISTEMA ROTA ASSESSORIA")
    print("=" * 50)

    test_imports()
    test_supabase_references()
    test_cache_manager()

    app = test_app_creation()
    test_routes_registration(app)

    print("\n" + "=" * 50)
    print("DIAGNOSTICO CONCLUIDO")