from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.models import Prefeitura
from src.schemas.schemas import PrefeituraResponse

router = APIRouter(prefix="/prefeituras", tags=["Prefeituras"])


@router.get("/", response_model=list[PrefeituraResponse])
def listar_prefeituras(db: Annotated[Session, Depends(get_db)]):
    """
    Lista as prefeituras cadastradas, para a empresa escolher o município
    no autocadastro (HU001).
    """
    return db.query(Prefeitura).order_by(Prefeitura.nome).all()
