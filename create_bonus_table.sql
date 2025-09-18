-- Criar tabela para bônus/missões dos assessores
CREATE TABLE IF NOT EXISTS public.bonus_missoes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    mes VARCHAR(7) NOT NULL, -- formato YYYY-MM
    nome_missao TEXT NOT NULL,
    valor_bonus DECIMAL(15,2) DEFAULT 0.00,
    origem VARCHAR(10) DEFAULT 'XP', -- XP ou SVN
    liquido_assessor BOOLEAN DEFAULT true, -- Se é líquido para o assessor ou valor bruto
    ativo BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Índices para melhor performance
CREATE INDEX IF NOT EXISTS idx_bonus_missoes_user_id ON public.bonus_missoes(user_id);
CREATE INDEX IF NOT EXISTS idx_bonus_missoes_mes ON public.bonus_missoes(mes);
CREATE INDEX IF NOT EXISTS idx_bonus_missoes_user_mes ON public.bonus_missoes(user_id, mes);

-- Comentários para documentação
COMMENT ON TABLE public.bonus_missoes IS 'Tabela para armazenar bônus e missões dos assessores por mês';
COMMENT ON COLUMN public.bonus_missoes.user_id IS 'ID do usuário/assessor';
COMMENT ON COLUMN public.bonus_missoes.mes IS 'Mês no formato YYYY-MM';
COMMENT ON COLUMN public.bonus_missoes.nome_missao IS 'Nome/descrição da missão ou bônus';
COMMENT ON COLUMN public.bonus_missoes.valor_bonus IS 'Valor do bônus em reais';
COMMENT ON COLUMN public.bonus_missoes.origem IS 'Origem do bônus: XP ou SVN';
COMMENT ON COLUMN public.bonus_missoes.liquido_assessor IS 'Se true: valor líquido; se false: valor bruto (aplica 80%)';
COMMENT ON COLUMN public.bonus_missoes.ativo IS 'Se o bônus/missão está ativo ou não';

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_bonus_missoes_updated_at
    BEFORE UPDATE ON public.bonus_missoes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();