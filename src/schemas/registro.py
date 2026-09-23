from datetime import datetime, timezone
import uuid
from decimal import Decimal
from pydantic import BaseModel, Field
from src.schemas.enums import Statusvalidacao

class Registro(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    Empresa_id: str = Field(..., min_length=1)
    validador_id: str = Field(..., min_length=1)
    material_id: str = Field(..., min_length=1)
    periodo: str = Field(..., min_length=1)
    volume_total: float = Field(..., gt=0)
    volume_validado: float = Field(..., gt=0)
    percentual_reciclado: float = Field(..., ge=0, le=100)
    status_validacao: Statusvalidacao = Field(default_factory=lambda: Statusvalidacao.AGUARDANDOVALIDACAO)
    motivo_rejeicao: str = Field(default=None)
    valorestimado: Decimal = Field(..., gt=0)
    carbonoevitado: float = Field(..., gt=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

