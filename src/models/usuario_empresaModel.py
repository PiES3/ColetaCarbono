from sqlalchemy.orm import declarative_base
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from src.core.database import Base
from src.schemas.enums import Perfil, StatusVinculo, StatusValidacao


Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

def get_utc_now():
    return datetime.now(timezone.utc)

class UsuarioEmpresa(Base):
    __tablename__ = "usuarios_empresa"

    id = Column(String, primary_key=True, default=generate_uuid)
    id_empresa = Column(String, ForeignKey("empresas.id"), nullable=False)
    nome = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    senha_hash = Column(String, nullable=False)
    perfil = Column(SQLEnum(Perfil), default=Perfil.COMUM)
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    # Relacionamentos
    empresa = relationship("Empresa", back_populates="usuarios")