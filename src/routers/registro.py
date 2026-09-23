# src/routers/registros.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from src.core.database import get_db
from src.models.models import Registro
from src.schemas.schemas import RegistroCreate, RegistroResponse
from src.services.services import registro_service
from pydantic import BaseModel

router = APIRouter(
    prefix="/registros",
    tags=["Registros"]
)

# Schema específico para a requisição de validação pelo Gestor
class ValidacaoRequest(BaseModel):
    validador_id: str
    volume_validado: float

@router.post("/", response_model=RegistroResponse, status_code=status.HTTP_201_CREATED)
def criar_registro(registro_in: RegistroCreate, db: Session = Depends(get_db)):
    """
    Recebe um novo registro (geralmente enviado pelo app mobile via sincronização).
    """
    novo_registro = Registro(
        empresa_id=registro_in.empresa_id,
        material_id=registro_in.material_id,
        periodo=registro_in.periodo,
        volume_total_original=registro_in.volume_total,
        percentual_reciclado=registro_in.percentual_reciclado
        # status_validacao já tem default 'PENDENTE' no banco
    )
    
    db.add(novo_registro)
    db.commit()
    db.refresh(novo_registro)
    
    return novo_registro

@router.get("/", response_model=List[RegistroResponse])
def listar_registros(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Lista todos os registros. Pode ser filtrado futuramente por empresa_id ou prefeitura.
    """
    registros = db.query(Registro).offset(skip).limit(limit).all()
    return registros

@router.patch("/{registro_id}/validar", response_model=RegistroResponse)
def validar_registro(
    registro_id: str, 
    dados_validacao: ValidacaoRequest,
    db: Session = Depends(get_db)
):
    """
    Endpoint utilizado pelo Gestor de Resíduos da Prefeitura para validar a pesagem.
    Executa o cálculo do carbono evitado e a estimativa financeira via RegistroService.
    """
    registro_atualizado = registro_service.validar_e_calcular(
        db=db,
        registro_id=registro_id,
        validador_id=dados_validacao.validador_id,
        volume_validado=dados_validacao.volume_validado
    )
    
    return registro_atualizado