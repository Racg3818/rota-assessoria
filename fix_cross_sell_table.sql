-- =========================================
-- FIX: Corrigir tipo de cliente_id na tabela cross_sell
-- =========================================
-- PROBLEMA: cliente_id estava definido como INTEGER, mas clientes.id é UUID
-- SOLUÇÃO: Recriar a tabela com o tipo correto

-- 1. Fazer backup dos dados existentes (se houver)
CREATE TEMP TABLE cross_sell_backup AS SELECT * FROM cross_sell;

-- 2. Remover policies antigas
DROP POLICY IF EXISTS "Users can view own cross_sell data" ON cross_sell;
DROP POLICY IF EXISTS "Users can insert own cross_sell data" ON cross_sell;
DROP POLICY IF EXISTS "Users can update own cross_sell data" ON cross_sell;
DROP POLICY IF EXISTS "Users can delete own cross_sell data" ON cross_sell;

-- 3. Remover tabela antiga
DROP TABLE IF EXISTS cross_sell;

-- 4. Recriar tabela com tipos corretos
CREATE TABLE cross_sell (
    id SERIAL PRIMARY KEY,
    cliente_id UUID NOT NULL,
    user_id UUID NOT NULL,
    fee_based VARCHAR(20) DEFAULT '',
    financial_planning VARCHAR(20) DEFAULT '',
    mb VARCHAR(20) DEFAULT '',
    offshore VARCHAR(20) DEFAULT '',
    produto_estruturado VARCHAR(20) DEFAULT '',
    asset VARCHAR(20) DEFAULT '',
    seguro_vida VARCHAR(20) DEFAULT '',
    consorcio VARCHAR(20) DEFAULT '',
    wealth VARCHAR(20) DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(cliente_id, user_id),
    CONSTRAINT cross_sell_fee_based_check CHECK (fee_based IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_financial_planning_check CHECK (financial_planning IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_mb_check CHECK (mb IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_offshore_check CHECK (offshore IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_produto_estruturado_check CHECK (produto_estruturado IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_asset_check CHECK (asset IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_seguro_vida_check CHECK (seguro_vida IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_consorcio_check CHECK (consorcio IN ('', 'Apresentado', 'Boletado')),
    CONSTRAINT cross_sell_wealth_check CHECK (wealth IN ('', 'Apresentado', 'Boletado'))
);

-- 5. Restaurar dados do backup (se houver)
-- NOTA: Só funciona se cliente_id no backup puder ser convertido para UUID
-- Se a tabela estava vazia, esta linha não fará nada
INSERT INTO cross_sell
SELECT * FROM cross_sell_backup
WHERE EXISTS (SELECT 1 FROM cross_sell_backup);

-- 6. Criar índices
CREATE INDEX IF NOT EXISTS idx_cross_sell_cliente_id ON cross_sell(cliente_id);
CREATE INDEX IF NOT EXISTS idx_cross_sell_user_id ON cross_sell(user_id);

-- 7. Habilitar RLS
ALTER TABLE cross_sell ENABLE ROW LEVEL SECURITY;

-- 8. Recriar policies
DROP POLICY IF EXISTS "Users can view own cross_sell data" ON cross_sell;
CREATE POLICY "Users can view own cross_sell data"
ON cross_sell FOR SELECT
USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own cross_sell data" ON cross_sell;
CREATE POLICY "Users can insert own cross_sell data"
ON cross_sell FOR INSERT
WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own cross_sell data" ON cross_sell;
CREATE POLICY "Users can update own cross_sell data"
ON cross_sell FOR UPDATE
USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own cross_sell data" ON cross_sell;
CREATE POLICY "Users can delete own cross_sell data"
ON cross_sell FOR DELETE
USING (auth.uid() = user_id);

-- 9. Limpar backup temporário
DROP TABLE IF EXISTS cross_sell_backup;

-- Verificação final
SELECT
    'Tabela cross_sell recriada com sucesso!' as status,
    COUNT(*) as total_registros
FROM cross_sell;