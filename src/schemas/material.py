from datetime import datetime, timezone
import uuid
from decimal import Decimal
from pydantic import BaseModel, Field

class Material(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    categoria: str = Field(..., min_length=1)
    fator_emissaoipcc: Decimal = Field(..., gt=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

