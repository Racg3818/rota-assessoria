# config.py
import os
from dotenv import load_dotenv, find_dotenv

# 1) tenta .env.local na raiz do projeto
load_dotenv(find_dotenv(".env.local", usecwd=True))
# 2) fallback para .env, se existir
load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "svninvest.com.br")
