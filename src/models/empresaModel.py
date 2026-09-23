import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from src.core.database import Base
from src.schemas.enums import Perfil, StatusVinculo, StatusValidacao

def generate_uuid():
    return str(uuid.uuid4())

def get_utc_now():
    return datetime.now(timezone.utc)

class Empresa(Base):
    __tablename__ = "empresas"

    id = Column(String, primary_key=True, default=generate_uuid)
    prefeitura_id = Column(String, ForeignKey("prefeituras.id"), nullable=False)
    nome = Column(String, nullable=False)
    cnpj = Column(String, nullable=False, unique=True)
    razao_social = Column(String, nullable=False)
    nome_fantasia = Column(String, nullable=False)
    telefone = Column(String, nullable=False)
    endereco = Column(String, nullable=False)
    pwd_hash = Column(String, nullable=False)
    empresa_status = Column(SQLEnum(StatusVinculo), default=StatusVinculo.AGUARDANDO_VALIDACAO)
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    # Relacionamentos
    prefeitura = relationship("Prefeitura", back_populates="empresas")
    usuarios = relationship("UsuarioEmpresa", back_populates="empresa")
    registros = relationship("Registro", back_populates="empresa")