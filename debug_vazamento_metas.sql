-- Script para investigar vazamento de metas entre usuários
-- Execute no SQL Editor do Supabase

-- 1. Ver estado atual da tabela metas_mensais
SELECT 'ESTADO ATUAL DA TABELA METAS_MENSAIS:' as info;
SELECT id, mes, meta_receita, user_id, created_at 
FROM metas_mensais 
ORDER BY created_at DESC;

-- 2. Verificar RLS na tabela
SELECT 'STATUS DO RLS:' as info;
SELECT schemaname, tablename, rowsecurity, hasrls 
FROM pg_tables 
WHERE tablename = 'metas_mensais';

-- 3. Ver políticas RLS ativas
SELECT 'POLÍTICAS RLS ATIVAS:' as info;
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies 
WHERE tablename = 'metas_mensais';

-- 4. Verificar quantas metas existem para setembro 2025
SELECT 'METAS PARA SETEMBRO 2025:' as info;
SELECT mes, user_id, meta_receita, created_at
FROM metas_mensais 
WHERE mes = '2025-09'
ORDER BY created_at;

-- 5. Verificar se há duplicatas (múltiplas metas para mesmo mês)
SELECT 'VERIFICAR DUPLICATAS:' as info;
SELECT mes, COUNT(*) as total_metas, COUNT(DISTINCT user_id) as usuarios_distintos
FROM metas_mensais 
GROUP BY mes 
HAVING COUNT(*) > 1;

-- 6. Ver todos os usuários únicos que têm metas
SELECT 'USUÁRIOS COM METAS:' as info;
SELECT DISTINCT user_id, COUNT(*) as total_metas
FROM metas_mensais 
GROUP BY user_id 
ORDER BY total_metas DESC;

-- 7. AÇÃO CORRETIVA: Se houver múltiplas metas para setembro, mantenha apenas uma por usuário
-- (Descomente apenas se necessário após análise)
-- DELETE FROM metas_mensais 
-- WHERE id NOT IN (
--     SELECT DISTINCT ON (user_id, mes) id 
--     FROM metas_mensais 
--     WHERE mes = '2025-09'
--     ORDER BY user_id, mes, created_at DESC
-- ) AND mes = '2025-09';

-- 8. Verificar constraints e índices
SELECT 'CONSTRAINTS E ÍNDICES:' as info;
SELECT conname, contype, pg_get_constraintdef(oid) as definition
FROM pg_constraint 
WHERE conrelid = 'metas_mensais'::regclass;