-- ===============================================
-- MIGRAÇÃO: Implementar tabela profiles + triggers
-- ===============================================

-- 1. CRIAR TABELA PROFILES
-- ===============================================
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    codigo_xp TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. ÍNDICES PARA PERFORMANCE
-- ===============================================
CREATE INDEX IF NOT EXISTS idx_profiles_email ON public.profiles(email);
CREATE INDEX IF NOT EXISTS idx_profiles_codigo_xp ON public.profiles(codigo_xp);

-- 3. ROW LEVEL SECURITY (RLS)
-- ===============================================
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Política: usuários podem ver apenas seu próprio perfil
CREATE POLICY "Users can view own profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);

-- Política: usuários podem atualizar apenas seu próprio perfil
CREATE POLICY "Users can update own profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

-- Política: apenas usuários autenticados podem inserir
CREATE POLICY "Users can insert own profile" ON public.profiles
    FOR INSERT WITH CHECK (auth.uid() = id);

-- 4. FUNÇÃO PARA SINCRONIZAR auth.users → profiles
-- ===============================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, nome, email, codigo_xp)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'nome', ''),
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'codigo_xp', '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 5. TRIGGER PARA AUTO-CRIAR PROFILES
-- ===============================================
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 6. FUNÇÃO PARA ATUALIZAR updated_at AUTOMATICAMENTE
-- ===============================================
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- 7. MIGRAR DADOS EXISTENTES (se necessário)
-- ===============================================
-- Este script irá popular a tabela profiles com dados do auth.users
-- NOTA: Execute apenas uma vez após criar a estrutura

INSERT INTO public.profiles (id, nome, email, codigo_xp)
SELECT
    au.id,
    COALESCE(au.raw_user_meta_data->>'nome', au.email) as nome,
    au.email,
    COALESCE(au.raw_user_meta_data->>'codigo_xp', '') as codigo_xp
FROM auth.users au
WHERE au.id NOT IN (SELECT id FROM public.profiles)
ON CONFLICT (id) DO NOTHING;

-- 8. GRANTS PARA AUTHENTICATED USERS
-- ===============================================
GRANT SELECT, INSERT, UPDATE ON public.profiles TO authenticated;
GRANT USAGE ON SCHEMA public TO authenticated;

-- ===============================================
-- VERIFICAÇÕES PÓS-MIGRAÇÃO
-- ===============================================

-- Verificar quantos usuários foram migrados
-- SELECT COUNT(*) as total_profiles FROM public.profiles;
-- SELECT COUNT(*) as total_auth_users FROM auth.users;

-- Verificar se RLS está ativo
-- SELECT schemaname, tablename, rowsecurity FROM pg_tables WHERE tablename = 'profiles';