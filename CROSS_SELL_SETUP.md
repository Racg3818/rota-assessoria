# Cross Sell e Insights - Setup Guide

## 🎯 Visão Geral

Foram criadas duas novas funcionalidades na seção de Clientes:

### 1. **Cross Sell** (`/clientes/cross-sell`)
Tela para gerenciar a apresentação de produtos aos clientes. Permite registrar o status de cada produto:
- **Em branco**: Produto não foi apresentado
- **Apresentado**: Cliente conhece o produto
- **Boletado**: Cliente contratou o produto

**Produtos rastreados:**
- Fee Based
- Financial Planning
- MB
- Offshore
- Produto Estruturado
- Asset
- Seguro de Vida
- Consórcio
- Wealth Management

### 2. **Insights** (`/clientes/insights`)
Análise inteligente que cruza dados dos clientes para identificar oportunidades de negócio:
- Clientes com NET > R$ 1M sem Financial Planning
- Clientes TRADICIONAL com NET > R$ 500K (candidatos a Fee Based)
- Clientes com NET > R$ 1M sem Offshore
- Clientes com NET > R$ 3M sem Asset apresentado
- Clientes com NET > R$ 300K sem Seguro de Vida
- Distribuição de modelos e estatísticas
- Clientes sem MB (oportunidade de expansão)

---

## 📋 Passo 1: Criar a Tabela no Supabase

Execute o seguinte SQL no **SQL Editor** do Supabase Dashboard:

```sql
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

-- Índices para melhorar performance
CREATE INDEX IF NOT EXISTS idx_cross_sell_cliente_id ON cross_sell(cliente_id);
CREATE INDEX IF NOT EXISTS idx_cross_sell_user_id ON cross_sell(user_id);

-- Habilitar RLS
ALTER TABLE cross_sell ENABLE ROW LEVEL SECURITY;

-- Policy: Usuários só podem ver seus próprios registros
DROP POLICY IF EXISTS "Users can view own cross_sell data" ON cross_sell;
CREATE POLICY "Users can view own cross_sell data"
ON cross_sell FOR SELECT
USING (auth.uid() = user_id);

-- Policy: Usuários só podem inserir seus próprios registros
DROP POLICY IF EXISTS "Users can insert own cross_sell data" ON cross_sell;
CREATE POLICY "Users can insert own cross_sell data"
ON cross_sell FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- Policy: Usuários só podem atualizar seus próprios registros
DROP POLICY IF EXISTS "Users can update own cross_sell data" ON cross_sell;
CREATE POLICY "Users can update own cross_sell data"
ON cross_sell FOR UPDATE
USING (auth.uid() = user_id);

-- Policy: Usuários só podem deletar seus próprios registros
DROP POLICY IF EXISTS "Users can delete own cross_sell data" ON cross_sell;
CREATE POLICY "Users can delete own cross_sell data"
ON cross_sell FOR DELETE
USING (auth.uid() = user_id);
```

---

## 🚀 Passo 2: Testar a Aplicação

1. Reinicie o servidor Flask:
   ```bash
   python app.py
   ```

2. Acesse a aplicação: `http://localhost:3001`

3. No menu lateral, você verá os novos itens sob **Clientes**:
   - **⭐ Supernova** - Gerenciar datas de supernova
   - **🎯 Cross Sell** - Gerenciar apresentação de produtos
   - **💡 Insights** - Ver análises e oportunidades

4. Teste o fluxo:
   - Vá para **Cross Sell**
   - Selecione status de produtos para alguns clientes
   - Clique em **💾 Salvar** para cada cliente
   - Vá para **Insights** e veja as oportunidades identificadas

---

## 📁 Arquivos Modificados/Criados

### Backend:
- **`views/clientes.py`**: Adicionadas rotas `/cross-sell`, `/cross-sell/salvar`, `/insights`

### Frontend:
- **`templates/clientes/cross_sell.html`**: Nova página de Cross Sell
- **`templates/clientes/insights.html`**: Nova página de Insights
- **`templates/clientes/index.html`**: Atualizada navegação
- **`templates/clientes/supernova.html`**: Atualizada navegação

### Database:
- **`create_cross_sell_table.py`**: Script helper para criar tabela (opcional)

---

## 🎨 Features Implementadas

### Cross Sell:
✅ Tabela interativa com todos os clientes
✅ Filtros por nome e letra inicial
✅ 9 produtos rastreáveis por cliente
✅ 3 estados: Em branco, Apresentado, Boletado
✅ Cores visuais para fácil identificação
✅ Salvamento individual por cliente
✅ Navegação integrada

### Insights:
✅ 8 tipos de insights inteligentes
✅ Priorização automática (Alta, Média, Info)
✅ Lista expansível de clientes por insight
✅ Cores e ícones por tipo de oportunidade
✅ Estatísticas gerais
✅ Estado vazio elegante quando não há insights

---

## 🔐 Segurança

- ✅ RLS (Row Level Security) habilitado
- ✅ Policies garantem isolamento por usuário
- ✅ Validação de ownership em todas as operações
- ✅ Constraints no banco para valores válidos

---

## 📊 Insights Disponíveis

| Insight | Critério | Prioridade |
|---------|----------|------------|
| Clientes com NET > 1M sem Financial Planning | NET ≥ R$ 1.000.000 | Alta |
| Clientes TRADICIONAL candidatos a Fee Based | Modelo TRADICIONAL + NET ≥ R$ 500.000 | Alta |
| Clientes sem Offshore | NET ≥ R$ 1.000.000 | Alta |
| Clientes com NET > 3M sem Asset | NET ≥ R$ 3.000.000 | Alta |
| Clientes sem Seguro de Vida | NET ≥ R$ 300.000 | Média |
| Distribuição de Modelos | Estatística geral | Info |
| Clientes sem MB | Sem código MB + NET ≥ R$ 100.000 | Média |

---

## 🎯 Próximos Passos

1. Execute o SQL no Supabase
2. Teste as funcionalidades
3. Popule dados de Cross Sell para alguns clientes
4. Observe os insights sendo gerados automaticamente
5. Use os insights para direcionar suas ações comerciais

---

## ❓ Troubleshooting

### Erro "Table does not exist"
- Execute o SQL fornecido no Supabase Dashboard

### Erro "Permission denied"
- Verifique se as policies foram criadas corretamente
- Confirme que o usuário está autenticado

### Insights não aparecem
- Certifique-se de ter clientes cadastrados
- Preencha dados de Cross Sell para alguns clientes
- Verifique se os clientes têm valores de NET preenchidos

---

## 📞 Suporte

Para dúvidas ou problemas, verifique:
1. Console do navegador (F12) para erros JavaScript
2. Logs do servidor Flask para erros backend
3. Supabase Dashboard > Logs para erros de database

---

**Desenvolvido com ❤️ por Claude Code**