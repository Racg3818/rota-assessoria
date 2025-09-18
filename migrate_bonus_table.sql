-- Script de migração para adicionar novos campos à tabela bonus_missoes
-- Execute este script no Supabase SQL Editor

-- Adicionar coluna origem se não existir
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='bonus_missoes' AND column_name='origem') THEN
        ALTER TABLE public.bonus_missoes
        ADD COLUMN origem VARCHAR(10) DEFAULT 'XP';
    END IF;
END $$;

-- Adicionar coluna liquido_assessor se não existir
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='bonus_missoes' AND column_name='liquido_assessor') THEN
        ALTER TABLE public.bonus_missoes
        ADD COLUMN liquido_assessor BOOLEAN DEFAULT true;
    END IF;
END $$;

-- Atualizar comentários
COMMENT ON COLUMN public.bonus_missoes.origem IS 'Origem do bônus: XP ou SVN';
COMMENT ON COLUMN public.bonus_missoes.liquido_assessor IS 'Se true: valor líquido; se false: valor bruto (aplica 80%)';

-- Atualizar registros existentes com valores padrão (caso necessário)
UPDATE public.bonus_missoes
SET origem = 'XP'
WHERE origem IS NULL;

UPDATE public.bonus_missoes
SET liquido_assessor = true
WHERE liquido_assessor IS NULL;