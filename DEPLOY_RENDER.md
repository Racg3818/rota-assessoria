# Deploy no Render - Instruções Completas

## 1. Criar Repositório GitHub

1. Acesse: https://github.com
2. Clique em "New repository"
3. Nome: `rota-assessoria`
4. Deixe público ou privado (sua escolha)
5. **NÃO** marque "Add README" nem ".gitignore"
6. Clique "Create repository"

## 2. Conectar Repositório Local

Execute no terminal (substitua SEU_USUARIO):

```bash
cd "C:\Users\renan\OneDrive\Desktop\rota-assessoria"
git remote add origin https://github.com/SEU_USUARIO/rota-assessoria.git
git branch -M main
git push -u origin main
```

## 3. Deploy no Render

### 3.1. Criar Conta
1. Acesse: https://render.com
2. Clique "Get Started for Free"
3. Use GitHub para facilitar

### 3.2. Criar Web Service
1. Dashboard → "New +" → "Web Service"
2. "Connect a repository" → Autorize o GitHub
3. Selecione `rota-assessoria`

### 3.3. Configurações do Service
- **Name:** `rota-assessoria` (ou qualquer nome)
- **Environment:** `Python 3`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app`
- **Instance Type:** `Free`

### 3.4. Variáveis de Ambiente
Clique em "Advanced" e adicione:

```
SUPABASE_URL=https://ldrlgppgvwqlleglndvm.supabase.co

SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxkcmxncHBndndxbGxlZ2xuZHZtIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NzAzNTQzOSwiZXhwIjoyMDcyNjExNDM5fQ.x9EOz99jsRTPc58QUw-RefrEEjP_gHCmF-cNH8JPb6Q

SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxkcmxncHBndndxbGxlZ2xuZHZtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTcwMzU0MzksImV4cCI6MjA3MjYxMTQzOX0.sXMkqUm3Pr7SiJVJdJtTVFGV_wIGvU0I_dqVr2N3_0U

ALLOWED_DOMAIN=svninvest.com.br

FLASK_ENV=production

PYTHON_VERSION=3.11.9
```

### 3.5. Deploy
1. Clique "Create Web Service"
2. O Render vai:
   - Clonar seu repositório
   - Instalar dependências
   - Iniciar a aplicação
3. Em ~5-10 minutos sua URL estará pronta!

## 4. Após o Deploy

- URL será algo como: `https://rota-assessoria-abc123.onrender.com`
- Teste o login com usuários @svninvest.com.br
- Verifique se os dados estão isolados entre usuários

## 5. Limitações da Versão Gratuita

- App "dorme" após 15min sem uso
- 750 horas/mês gratuitas
- Deploy automático sempre que você fizer push no GitHub

## 6. Updates Futuros

Para atualizar:
1. Faça mudanças no código
2. `git add .`
3. `git commit -m "Update"`
4. `git push origin main`
5. Render fará deploy automático!

---

✅ **Arquivos preparados para deploy:**
- requirements.txt
- Procfile  
- runtime.txt
- .gitignore
- Git repository inicializado

**Próximo passo:** Siga as instruções acima! 🚀