from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field
from src.schemas.enums import StatusEmpresa

class Empresa(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prefeitura_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nome: str = Field(..., min_length=1)
    cnpj: str = Field(..., min_length=1)
    razao_social: str = Field(..., min_length=1)
    nome_fantasia: str = Field(..., min_length=1)
    telefone: str = Field(..., min_length=1)
    endereco: str = Field(..., min_length=1)
    pwd_hash: str = Field(..., min_length=1)
    empresa_status: StatusEmpresa = Field(default_factory=lambda: StatusEmpresa.AGUARDANDOVALIDACAO)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )