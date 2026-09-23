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

class Material(Base):
    __tablename__ = "materiais"

    id = Column(String, primary_key=True, default=generate_uuid)
    categoria = Column(String, nullable=False)
    fator_emissaoipcc = Column(Float, nullable=False) 
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    registros = relationship("Registro", back_populates="material")