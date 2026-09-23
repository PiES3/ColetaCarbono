from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from src.core.database import get_db
from src.models.models import Material
from src.schemas.schemas import MaterialCreate, MaterialResponse

router = APIRouter(
    prefix="/materiais",
    tags=["Materiais"]
)

@router.post("/", response_model=MaterialResponse, status_code=status.HTTP_201_CREATED)
def criar_material(material_in: MaterialCreate, db: Session = Depends(get_db)):
    """
    Cria um novo material e o seu respetivo fator de emissão IPCC.
    Geralmente acedido apenas por Superutilizadores.
    """
    novo_material = Material(**material_in.model_dump())
    
    db.add(novo_material)
    db.commit()
    db.refresh(novo_material)
    
    return novo_material

@router.get("/", response_model=List[MaterialResponse])
def listar_materiais(db: Session = Depends(get_db)):
    """
    Lista todos os materiais cadastrados.
    Utilizado pela aplicação móvel para popular as listas de seleção (dropdowns).
    """
    materiais = db.query(Material).all()
    return materiais