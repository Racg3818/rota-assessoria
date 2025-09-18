# 🎯 Migração do Sistema de Bônus

## 📋 Status Atual

O sistema de bônus foi implementado com **retrocompatibilidade completa**. Ele funciona em dois modos:

### ✅ Modo Básico (Atual)
- ✅ Cadastro de bônus com nome e valor
- ✅ Ativação/desativação de bônus
- ✅ Exclusão de bônus
- ✅ Integração com receitas do Dashboard e Simulador
- ❌ Campos Origem (XP/SVN) e cálculo de IR não disponíveis

### 🚀 Modo Completo (Após Migração)
- ✅ Todas as funcionalidades do modo básico
- ✅ Campo "Origem" (XP ou SVN)
- ✅ Campo "Líquido Assessor" (cálculo automático de 80% para valores brutos)
- ✅ Edição completa de bônus
- ✅ Interface visual aprimorada

## 🔧 Como Fazer a Migração

### 1. Acesse o Supabase
- Entre no painel do seu projeto Supabase
- Vá para **SQL Editor**

### 2. Execute o Script de Migração
- Copie e cole o conteúdo do arquivo `migrate_bonus_table.sql`
- Execute o script
- Aguarde a confirmação de sucesso

### 3. Reinicie a Aplicação
- Reinicie o Flask para atualizar o cache do schema
- Teste as novas funcionalidades

## 📁 Arquivos da Migração

### `migrate_bonus_table.sql`
Script seguro que adiciona as colunas sem afetar dados existentes:
- Adiciona coluna `origem` (padrão: 'XP')
- Adiciona coluna `liquido_assessor` (padrão: true)
- Atualiza registros existentes com valores padrão

### `create_bonus_table.sql`
Script completo para criar a tabela do zero (apenas para novos projetos).

## 🔍 Verificação da Migração

Após executar a migração, verifique se:

1. ✅ O aviso amarelo desaparece da tela de bônus
2. ✅ Formulários mostram campos "Origem" e "Tipo de Valor"
3. ✅ Tabela mostra colunas "Origem", "Valor Cadastrado" e "Valor Líquido"
4. ✅ Botão "Editar" funciona corretamente
5. ✅ Cálculo de 80% funciona para valores brutos

## 🚨 Importante

- ⚠️ **A migração é segura**: não remove nem altera dados existentes
- ⚠️ **Backup recomendado**: sempre faça backup antes de executar scripts
- ⚠️ **Teste primeiro**: execute em ambiente de teste se possível

## 📞 Suporte

Se encontrar problemas:
1. Verifique os logs da aplicação Flask
2. Confirme que as colunas foram criadas no Supabase
3. Reinicie a aplicação após a migração