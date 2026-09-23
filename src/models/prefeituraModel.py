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


class Prefeitura(Base):
    __tablename__ = "prefeituras"

    id = Column(String, primary_key=True, default=generate_uuid)
    nome = Column(String, nullable=False)
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    # Relacionamentos
    empresas = relationship("Empresa", back_populates="prefeitura")
    administradores = relationship("UsuarioAdmin", back_populates="prefeitura")
