#!/usr/bin/env python3
"""
Script para diagnosticar o problema de autenticação e isolamento de usuários
"""
import os
import hashlib
from datetime import datetime

# Configurar environment
os.environ['SUPABASE_URL'] = 'https://ldrlgppgvwqlleglndvm.supabase.co'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxkcmxncHBndndxbGxlZ2xuZHZtIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NzAzNTQzOSwiZXhwIjoyMDcyNjExNDM5fQ.x9EOz99jsRTPc58QUw-RefrEEjP_gHCmF-cNH8JPb6Q'

try:
    from supabase_client import supabase_admin
    
    print("=== DIAGNÓSTICO DE AUTENTICAÇÃO E ISOLAMENTO ===")
    print(f"Data/hora: {datetime.now()}")
    print()
    
    # 1. Verificar todos os usuários no Supabase Auth
    print("1. USUÁRIOS NO SUPABASE AUTH:")
    try:
        users_list = supabase_admin.auth.admin.list_users()
        if hasattr(users_list, 'data') and users_list.data:
            users = users_list.data.get('users', [])
            print(f"   Total de usuários: {len(users)}")
            for i, user in enumerate(users):
                print(f"   [{i+1}] ID: {user.get('id')}")
                print(f"        Email: {user.get('email')}")
                print(f"        Metadata: {user.get('user_metadata', {})}")
                print(f"        Created: {user.get('created_at')}")
                print()
        else:
            print("   Nenhum usuário encontrado ou erro ao listar")
    except Exception as e:
        print(f"   ERRO ao listar usuários: {e}")
    
    # 2. Verificar todas as metas na tabela
    print("2. METAS NA TABELA metas_mensais:")
    try:
        metas = supabase_admin.table('metas_mensais').select('*').execute()
        if metas.data:
            print(f"   Total de metas: {len(metas.data)}")
            for i, meta in enumerate(metas.data):
                print(f"   [{i+1}] ID: {meta.get('id')}")
                print(f"        Mês: {meta.get('mes')}")
                print(f"        Meta: {meta.get('meta_receita')}")
                print(f"        User ID: {meta.get('user_id')}")
                print()
        else:
            print("   Nenhuma meta encontrada")
    except Exception as e:
        print(f"   ERRO ao listar metas: {e}")
    
    # 3. Simular processo de autenticação para dois usuários diferentes
    print("3. SIMULAÇÃO DE AUTENTICAÇÃO:")
    test_users = [
        {"email": "user1@svninvest.com.br", "nome": "Usuario 1", "codigo_xp": "12345"},
        {"email": "user2@svninvest.com.br", "nome": "Usuario 2", "codigo_xp": "67890"}
    ]
    
    for i, user_data in enumerate(test_users):
        print(f"   Usuário {i+1}: {user_data['email']}")
        
        # Fallback ID (se a autenticação Supabase falhar)
        fallback_id = hashlib.sha256(user_data['email'].encode()).hexdigest()[:32]
        print(f"     Fallback ID: {fallback_id}")
        
        # Verificar se o usuário já existe no Supabase
        temp_password = f"temp_{user_data['codigo_xp']}_default"
        print(f"     Senha temporária: {temp_password}")
        
        try:
            # Tentar encontrar usuário existente por email
            found_user = supabase_admin.auth.admin.list_users(email=user_data['email'])
            if hasattr(found_user, 'data') and found_user.data:
                users = found_user.data.get('users', [])
                if users:
                    print(f"     ⚠️  Usuário JÁ EXISTE: {users[0].get('id')}")
                    print(f"     ⚠️  Metadata: {users[0].get('user_metadata', {})}")
                else:
                    print(f"     ✅ Usuário NÃO existe - seria criado novo")
            else:
                print(f"     ✅ Usuário NÃO existe - seria criado novo")
        except Exception as e:
            print(f"     ERRO ao verificar usuário: {e}")
        
        print()
    
    # 4. Identificar possíveis causas do vazamento
    print("4. ANÁLISE DE POSSÍVEIS CAUSAS:")
    print("   a) Se ambos os usuários têm o MESMO user_id → PROBLEMA GRAVE")
    print("   b) Se RLS não está funcionando → user_id diferente mas dados vazam")
    print("   c) Se filtros explícitos falham → bug na query")
    print("   d) Se cache/sessão está contaminada → problema na aplicação")
    print()
    
    print("=== FIM DO DIAGNÓSTICO ===")
    
except Exception as e:
    print(f"ERRO GERAL: {e}")
    import traceback
    traceback.print_exc()