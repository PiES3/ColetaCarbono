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

class Registro(Base):
    __tablename__ = "registros"

    id = Column(String, primary_key=True, default=generate_uuid)
    empresa_id = Column(String, ForeignKey("empresas.id"), nullable=False)
    validador_id = Column(String, ForeignKey("usuarios_admin.id"), nullable=True) # Permite null até ser validado
    material_id = Column(String, ForeignKey("materiais.id"), nullable=False)
    periodo = Column(String, nullable=False)
    volume_total = Column(Float, nullable=False)
    volume_validado = Column(Float, nullable=True)
    percentual_reciclado = Column(Float, nullable=False)
    status_validacao = Column(SQLEnum(StatusValidacao), default=StatusValidacao.PENDENTE)
    motivo_rejeicao = Column(String, nullable=True)
    
    # Valores calculados após a validação
    valorestimado = Column(Float, nullable=True) 
    carbonoevitado = Column(Float, nullable=True) 
    
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    # Relacionamentos
    empresa = relationship("Empresa", back_populates="registros")
    validador = relationship("UsuarioAdmin", back_populates="registros_validados")
    material = relationship("Material", back_populates="registros")