from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(255), nullable=False)  # ID do usuário proprietário
    codigo_xp = db.Column(db.String(50))
    codigo_mb = db.Column(db.String(50))
    nome = db.Column(db.String(255), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)  # TRADICIONAL, ASSET, FEE_BASED, FEE_BASED_SEM_RV
    repasse = db.Column(db.Integer, nullable=False, default=35) # 35 ou 50
    net_xp = db.Column(db.Float, default=0.0)
    net_xp_global = db.Column(db.Float, default=0.0)
    net_mb = db.Column(db.Float, default=0.0)
    net_total = db.Column(db.Float, default=0.0)

class ReceitaItem(db.Model):
    __tablename__ = "receita_itens"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(255), nullable=False)  # ID do usuário proprietário
    data_ref = db.Column(db.String(7), nullable=False)  # 'YYYY-MM'
    cliente_codigo = db.Column(db.String(50))
    cliente_nome = db.Column(db.String(255))
    origem = db.Column(db.String(100))
    familia = db.Column(db.String(100))
    produto = db.Column(db.String(255))
    categoria = db.Column(db.String(100))
    detalhe = db.Column(db.String(255))
    valor_bruto = db.Column(db.Float)
    imposto_pct = db.Column(db.Float)
    valor_liquido = db.Column(db.Float)
    comissao_bruta = db.Column(db.Float)
    comissao_liquida = db.Column(db.Float)
    comissao_escritorio = db.Column(db.Float)
    modelo = db.Column(db.String(50))

class MetaMensal(db.Model):
    __tablename__ = "metas_mensais"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)  # ID do usuário proprietário
    mes = db.Column(db.String(7), nullable=False) # 'YYYY-MM'
    meta_receita = db.Column(db.Float, nullable=False, default=0.0)

class Produto(db.Model):
    __tablename__ = "produtos"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(255), nullable=False)  # ID do usuário proprietário
    nome = db.Column(db.String(255), nullable=False)
    classe = db.Column(db.String(50), nullable=False)  # RF, Fundos, Previdência, RV(mesa), Estruturado, COE, FII, Offshore, Seguro, Consórcio
    roa_pct = db.Column(db.Float, nullable=False, default=0.0)  # ex: 1.2 => 1.2%
    em_campanha = db.Column(db.Boolean, default=False)
    campanha_mes = db.Column(db.String(7))  # 'YYYY-MM' quando em campanha (opcional)

class Alocacao(db.Model):
    __tablename__ = "alocacoes"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(255), nullable=False)  # ID do usuário proprietário
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=False)
    percentual = db.Column(db.Float, default=0.0)  # % da carteira do cliente nesse produto
    valor = db.Column(db.Float, default=0.0)  # valor da alocação
    efetivada = db.Column(db.Boolean, default=False)  # confirmação final
    status = db.Column(db.String(50), default='mapeado')  # mapeado, apresentado, push_enviado, confirmado

    cliente = db.relationship("Cliente", backref=db.backref("alocacoes", cascade="all, delete-orphan"))
    produto = db.relationship("Produto")