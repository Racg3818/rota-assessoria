"""
Sistema local de usuários para quando o Supabase falha.
Permite que o sistema continue funcionando usando arquivos locais.
"""

import hashlib
import uuid
import json
import os
from typing import Dict, Optional
from flask import current_app

# Arquivo local para armazenar dados de usuários
USER_DATA_FILE = "local_users.json"

def generate_deterministic_user_id(email: str) -> str:
    """Gera um user_id determinístico baseado no email."""
    email_hash = hashlib.sha256(email.encode()).digest()
    return str(uuid.UUID(bytes=email_hash[:16]))

def load_local_users() -> Dict:
    """Carrega dados de usuários do arquivo local."""
    try:
        if os.path.exists(USER_DATA_FILE):
            with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        if current_app:
            current_app.logger.warning("LOCAL_USER: Erro ao carregar dados locais: %s", e)
    return {}

def save_local_users(users_data: Dict):
    """Salva dados de usuários no arquivo local."""
    try:
        with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        if current_app:
            current_app.logger.error("LOCAL_USER: Erro ao salvar dados locais: %s", e)

def get_or_create_local_user(email: str, nome: str = None, codigo_xp: str = None) -> str:
    """
    Obtém ou cria um usuário local quando o Supabase não está disponível.
    Retorna o user_id determinístico.
    """
    users_data = load_local_users()

    # Gerar ID determinístico
    user_id = generate_deterministic_user_id(email)

    # Verificar se usuário já existe
    if user_id not in users_data:
        # Criar novo usuário local
        users_data[user_id] = {
            'email': email,
            'nome': nome or email.split('@')[0],
            'codigo_xp': codigo_xp or '',
            'created_at': str(uuid.uuid4()),  # Timestamp simulado
            'is_local': True  # Marca como usuário local
        }
        save_local_users(users_data)

        if current_app:
            current_app.logger.info("LOCAL_USER: Criado usuário local: %s -> %s", email, user_id)
    else:
        # Atualizar dados se necessário
        updated = False
        if nome and users_data[user_id].get('nome') != nome:
            users_data[user_id]['nome'] = nome
            updated = True
        if codigo_xp and users_data[user_id].get('codigo_xp') != codigo_xp:
            users_data[user_id]['codigo_xp'] = codigo_xp
            updated = True

        if updated:
            save_local_users(users_data)
            if current_app:
                current_app.logger.info("LOCAL_USER: Atualizado usuário local: %s", email)

    return user_id

def validate_local_user_id(user_id: str) -> bool:
    """Valida se um user_id existe no sistema local."""
    if not user_id:
        return False

    users_data = load_local_users()
    return user_id in users_data

def get_local_user_data(user_id: str) -> Optional[Dict]:
    """Obtém dados de um usuário local."""
    users_data = load_local_users()
    return users_data.get(user_id)

def create_mock_data_for_user(user_id: str, email: str):
    """
    Cria dados mock básicos para um usuário quando o Supabase não está disponível.
    Isso permite que o sistema continue funcionando para demonstração.
    """
    try:
        # Criar estrutura de dados mock
        mock_data = {
            'clientes': [],
            'produtos': [
                {
                    'id': 1,
                    'nome': 'Produto Demo',
                    'classe': 'demo',
                    'roa_pct': 1.0,
                    'user_id': user_id
                }
            ],
            'metas_mensais': [],
            'alocacoes': []
        }

        # Salvar em arquivo específico do usuário
        mock_file = f"mock_data_{user_id}.json"
        with open(mock_file, 'w', encoding='utf-8') as f:
            json.dump(mock_data, f, indent=2)

        if current_app:
            current_app.logger.info("LOCAL_USER: Dados mock criados para %s: %s", email, mock_file)

    except Exception as e:
        if current_app:
            current_app.logger.error("LOCAL_USER: Erro ao criar dados mock: %s", e)