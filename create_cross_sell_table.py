from supabase_client import supabase_admin

# Criar a tabela usando insert/select (workaround)
try:
    # Verificar se a tabela já existe
    result = supabase_admin.table('cross_sell').select('id').limit(1).execute()
    print("Tabela cross_sell ja existe!")
except Exception as e:
    print(f"Erro ao verificar tabela: {e}")
    print("\nPor favor, execute o seguinte SQL no Supabase Dashboard:\n")
    print("""
-- Criar tabela cross_sell
CREATE TABLE IF NOT EXISTS cross_sell (
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

-- Indices para melhorar performance
CREATE INDEX IF NOT EXISTS idx_cross_sell_cliente_id ON cross_sell(cliente_id);
CREATE INDEX IF NOT EXISTS idx_cross_sell_user_id ON cross_sell(user_id);

-- Habilitar RLS
ALTER TABLE cross_sell ENABLE ROW LEVEL SECURITY;

-- Policy: Usuarios so podem ver seus proprios registros
DROP POLICY IF EXISTS "Users can view own cross_sell data" ON cross_sell;
CREATE POLICY "Users can view own cross_sell data"
ON cross_sell FOR SELECT
USING (auth.uid() = user_id);

-- Policy: Usuarios so podem inserir seus proprios registros
DROP POLICY IF EXISTS "Users can insert own cross_sell data" ON cross_sell;
CREATE POLICY "Users can insert own cross_sell data"
ON cross_sell FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- Policy: Usuarios so podem atualizar seus proprios registros
DROP POLICY IF EXISTS "Users can update own cross_sell data" ON cross_sell;
CREATE POLICY "Users can update own cross_sell data"
ON cross_sell FOR UPDATE
USING (auth.uid() = user_id);

-- Policy: Usuarios so podem deletar seus proprios registros
DROP POLICY IF EXISTS "Users can delete own cross_sell data" ON cross_sell;
CREATE POLICY "Users can delete own cross_sell data"
ON cross_sell FOR DELETE
USING (auth.uid() = user_id);
""")