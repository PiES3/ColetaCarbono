from datetime import datetime, timezone
import uuid
from src.schemas.enums import Perfil

from pydantic import BaseModel, Field

class UsuarioAdmin(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nome: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    id_prefeitura: str = Field(default_factory=lambda: str(uuid.uuid4()))
    senha_hash: str = Field(..., min_length=1)
    perfis: Perfil = Field(default_factory=lambda: Perfil.COMUM)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )