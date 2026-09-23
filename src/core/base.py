import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def gen_uuid() -> str:
    return str(uuid.uuid4())

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    """Mixin para adicionar automaticamente datas de criação, atualização e eliminação lógica"""
    created_at: Mapped[datetime] = mapped_column(default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        default=get_utc_now, onupdate=get_utc_now
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)