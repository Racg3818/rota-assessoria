-- Script para debugar problemas com metas_mensais
-- Execute no SQL Editor do Supabase

-- 1. Verificar estrutura da tabela
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'metas_mensais' 
ORDER BY ordinal_position;

-- 2. Verificar dados existentes
SELECT id, mes, meta_receita, user_id, created_at
FROM metas_mensais 
ORDER BY created_at DESC;

-- 3. Verificar se existem duplicatas por (user_id, mes)
SELECT user_id, mes, COUNT(*) as count
FROM metas_mensais 
GROUP BY user_id, mes 
HAVING COUNT(*) > 1;

-- 4. Verificar índices existentes
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'metas_mensais';

-- 5. Adicionar coluna user_id se não existir
ALTER TABLE metas_mensais ADD COLUMN IF NOT EXISTS user_id text;

-- 6. Criar índice único para evitar duplicatas (se não existir)
CREATE UNIQUE INDEX IF NOT EXISTS metas_mensais_user_mes_unique 
ON metas_mensais (user_id, mes);

-- 7. Verificar dados órfãos (sem user_id)
SELECT COUNT(*) as dados_sem_user_id
FROM metas_mensais 
WHERE user_id IS NULL;

-- 8. Se houver dados órfãos, você pode atribuí-los a um usuário específico:
-- UPDATE metas_mensais SET user_id = 'SEU_USER_ID_AQUI' WHERE user_id IS NULL;