#!/usr/bin/env python3
"""
Script para diagnosticar conectividade com Supabase
Execute: python test_supabase_connection.py
"""
import os
import sys
import socket
import requests
from urllib.parse import urlparse

def test_dns_resolution():
    """Testa resolução DNS"""
    print("=== 1. TESTE DE DNS ===")
    try:
        url = os.getenv("SUPABASE_URL", "https://ldrlgppgvwqlleglndvm.supabase.co")
        hostname = urlparse(url).hostname
        ip = socket.gethostbyname(hostname)
        print(f"✅ DNS OK: {hostname} -> {ip}")
        return True
    except socket.gaierror as e:
        print(f"❌ ERRO DNS: {e}")
        print("💡 SOLUÇÃO: Verifique sua conexão com internet")
        return False

def test_http_connection():
    """Testa conectividade HTTP"""
    print("\n=== 2. TESTE HTTP ===")
    try:
        url = os.getenv("SUPABASE_URL", "https://ldrlgppgvwqlleglndvm.supabase.co")
        response = requests.get(f"{url}/rest/v1/", timeout=10)
        print(f"✅ HTTP OK: Status {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ ERRO HTTP: {e}")
        print("💡 SOLUÇÃO: Verifique proxy/firewall")
        return False

def test_supabase_client():
    """Testa cliente Supabase"""
    print("\n=== 3. TESTE SUPABASE CLIENT ===")
    try:
        # Importa como na aplicação
        sys.path.insert(0, os.path.dirname(__file__))
        from supabase_client import supabase
        
        # Testa uma consulta simples
        result = supabase.table("clientes").select("id").limit(1).execute()
        print(f"✅ SUPABASE OK: {len(result.data or [])} registros encontrados")
        return True
    except Exception as e:
        print(f"❌ ERRO SUPABASE: {e}")
        return False

def test_environment():
    """Verifica variáveis de ambiente"""
    print("\n=== 4. TESTE AMBIENTE ===")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not url:
        print("❌ SUPABASE_URL não definida")
        return False
    if not key:
        print("❌ SUPABASE_SERVICE_ROLE_KEY não definida")
        return False
        
    print(f"✅ SUPABASE_URL: {url}")
    print(f"✅ SUPABASE_SERVICE_ROLE_KEY: {key[:20]}...")
    return True

def main():
    print("🔍 DIAGNÓSTICO DE CONECTIVIDADE SUPABASE")
    print("=" * 50)
    
    # Carrega .env.local se existir
    env_file = os.path.join(os.path.dirname(__file__), '.env.local')
    if os.path.exists(env_file):
        print(f"📁 Carregando {env_file}")
        with open(env_file) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
    
    success = True
    success &= test_environment()
    success &= test_dns_resolution()
    success &= test_http_connection()
    success &= test_supabase_client()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 TODOS OS TESTES PASSARAM!")
        print("✅ Supabase está acessível")
    else:
        print("❌ ALGUNS TESTES FALHARAM!")
        print("💡 Siga as soluções sugeridas acima")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())