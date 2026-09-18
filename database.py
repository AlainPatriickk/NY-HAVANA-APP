import os
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(application):
  db_url = os.environ.get("DATABASE_URL")
  if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

  application.config["SQLALCHEMY_DATABASE_URI"] = (
      db_url or "sqlite:///ny_havana.db"
  )
  db.init_app(application)
class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    nom_assure = db.Column(db.String(255), nullable=False, unique=True)
    adresse = db.Column(db.String(255), nullable=True)
    contact = db.Column(db.String(50), nullable=True)
    quittances = db.relationship('Quittance', backref='client', lazy=True)

class Quittance(db.Model):
    __tablename__ = 'quittances'
    id = db.Column(db.Integer, primary_key=True)
    police = db.Column(db.String(100), nullable=False, index=True)
    quittance_num = db.Column(db.String(100), nullable=False, unique=True)
    branche = db.Column(db.String(50), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    prime_totale = db.Column(db.Float, nullable=False, default=0.0)
    encaisse = db.Column(db.Float, nullable=False, default=0.0)
    reliquat = db.Column(db.Float, nullable=False, default=0.0)
    etat = db.Column(db.String(50), default='Impayé')
    
    id_client = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)

class HistoriqueDocument(db.Model):
    __tablename__ = 'historiques'
    id = db.Column(db.Integer, primary_key=True)
    type_doc = db.Column(db.String(20), nullable=False)
    reference = db.Column(db.String(100), nullable=False)
    police = db.Column(db.String(100), nullable=True)
    nom_assure = db.Column(db.String(255), nullable=False)
    date_generation = db.Column(db.DateTime, server_default=db.func.now())
    chemin_pdf = db.Column(db.String(255), nullable=True)
