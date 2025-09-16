"""
Sistema de cache centralizado para otimizar performance do Rota Assessoria.
Usa Flask-Caching com TTL configurável e invalidação automática.
"""
import os
import hashlib
from functools import wraps
from flask import current_app, session
from flask_caching import Cache

# Configuração do cache
cache = Cache()

# TTL padrões (em segundos)
CACHE_TIMEOUTS = {
    'clientes_list': 15 * 60,      # 15 minutos - muda pouco
    'produtos_list': 20 * 60,      # 20 minutos - muda pouco
    'receitas_calc': 5 * 60,       # 5 minutos - cálculos pesados
    'dashboard_data': 10 * 60,     # 10 minutos - dados agregados
    'metas_data': 30 * 60,         # 30 minutos - metas mensais
    'user_metadata': 60 * 60,      # 1 hora - metadados do usuário
}

def get_user_id():
    """Obtém ID do usuário da sessão."""
    try:
        u = session.get("user") or {}
        return u.get("id") or u.get("supabase_user_id")
    except RuntimeError:
        # Fora do contexto de requisição
        return None

def make_cache_key(prefix: str, *args, **kwargs):
    """
    Gera chave única de cache baseada no usuário e parâmetros.

    Args:
        prefix: Prefixo da chave (ex: 'clientes_list')
        *args: Argumentos posicionais
        **kwargs: Argumentos nomeados

    Returns:
        str: Chave única para o cache
    """
    uid = get_user_id()
    if not uid:
        return None

    # Criar string única com todos os parâmetros
    key_parts = [prefix, str(uid)]
    key_parts.extend(str(arg) for arg in args)

    # Adicionar kwargs ordenados
    for k in sorted(kwargs.keys()):
        key_parts.append(f"{k}:{kwargs[k]}")

    key_string = "|".join(key_parts)

    # Hash para evitar chaves muito longas
    key_hash = hashlib.md5(key_string.encode()).hexdigest()
    return f"rota:{prefix}:{uid}:{key_hash}"

def cached_by_user(cache_key_prefix: str, timeout: int = None):
    """
    Decorator para cache por usuário com TTL configurável.

    Args:
        cache_key_prefix: Prefixo da chave (deve estar em CACHE_TIMEOUTS)
        timeout: TTL customizado em segundos (opcional)

    Usage:
        @cached_by_user('clientes_list')
        def get_clientes():
            return expensive_database_call()
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Verificar se usuário está logado
            uid = get_user_id()
            if not uid:
                current_app.logger.warning(f"Cache skip: sem user_id para {func.__name__}")
                return func(*args, **kwargs)

            # Gerar chave do cache
            cache_key = make_cache_key(cache_key_prefix, *args, **kwargs)
            if not cache_key:
                return func(*args, **kwargs)

            # Tentar buscar no cache
            try:
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    current_app.logger.info(f"Cache HIT: {cache_key}")
                    return cached_result
            except Exception as e:
                current_app.logger.warning(f"Cache GET failed for {cache_key}: {e}")

            # Cache miss - executar função
            current_app.logger.info(f"Cache MISS: {cache_key}")
            result = func(*args, **kwargs)

            # Salvar no cache
            try:
                ttl = timeout or CACHE_TIMEOUTS.get(cache_key_prefix, 300)  # 5min default
                cache.set(cache_key, result, timeout=ttl)
                current_app.logger.info(f"Cache SET: {cache_key} (TTL: {ttl}s)")
            except Exception as e:
                current_app.logger.warning(f"Cache SET failed for {cache_key}: {e}")

            return result
        return wrapper
    return decorator

def invalidate_user_cache(cache_key_prefix: str, *args, **kwargs):
    """
    Invalida cache específico do usuário.

    Args:
        cache_key_prefix: Prefixo da chave a invalidar
        *args, **kwargs: Parâmetros para gerar a chave exata
    """
    uid = get_user_id()
    if not uid:
        return False

    cache_key = make_cache_key(cache_key_prefix, *args, **kwargs)
    if not cache_key:
        return False

    try:
        cache.delete(cache_key)
        current_app.logger.info(f"Cache INVALIDATED: {cache_key}")
        return True
    except Exception as e:
        current_app.logger.warning(f"Cache invalidation failed for {cache_key}: {e}")
        return False

def invalidate_all_user_cache():
    """
    Invalida todo o cache do usuário atual.
    Útil quando há mudanças que afetam múltiplas áreas.
    """
    uid = get_user_id()
    if not uid:
        return False

    try:
        # Invalidar por prefixos conhecidos
        prefixes = list(CACHE_TIMEOUTS.keys())
        count = 0

        for prefix in prefixes:
            pattern = f"rota:{prefix}:{uid}:*"
            # Note: Este método pode não funcionar em todos os backends
            # Para Redis, seria diferente. Por simplicidade, fazemos individual.
            try:
                cache.delete_many(pattern)
                count += 1
            except Exception:
                # Fallback: tentar invalidar chaves comuns
                for common_key in [make_cache_key(prefix)]:
                    if common_key:
                        cache.delete(common_key)

        current_app.logger.info(f"Cache BULK INVALIDATED: {count} patterns for user {uid}")
        return True
    except Exception as e:
        current_app.logger.warning(f"Bulk cache invalidation failed: {e}")
        return False

def cache_stats():
    """
    Retorna estatísticas do cache (se suportado pelo backend).
    """
    try:
        # Implementação básica - pode ser expandida conforme backend
        return {
            "status": "active",
            "backend": cache.config.get('CACHE_TYPE', 'unknown'),
            "user_id": get_user_id()
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "user_id": get_user_id()
        }

def init_cache(app):
    """
    Inicializa o sistema de cache com a aplicação Flask.

    Args:
        app: Instância da aplicação Flask
    """
    # Configuração baseada no ambiente
    cache_config = {
        'CACHE_TYPE': os.getenv('CACHE_TYPE', 'simple'),  # simple, redis, memcached
        'CACHE_DEFAULT_TIMEOUT': 300,  # 5 minutos default
    }

    # Configurações específicas por tipo
    if cache_config['CACHE_TYPE'] == 'redis':
        cache_config.update({
            'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
            'CACHE_KEY_PREFIX': 'rota_cache:'
        })
    elif cache_config['CACHE_TYPE'] == 'memcached':
        cache_config.update({
            'CACHE_MEMCACHED_SERVERS': [os.getenv('MEMCACHED_SERVERS', '127.0.0.1:11211')]
        })

    # Inicializar cache
    cache.init_app(app, config=cache_config)

    app.logger.info(f"Cache inicializado: {cache_config['CACHE_TYPE']}")

    return cache