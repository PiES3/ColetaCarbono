from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import get_current_user, require_superuser
from src.models.models import Material, Registro
from src.schemas.schemas import MaterialCreate, MaterialResponse, MaterialUpdate

router = APIRouter(prefix="/materiais", tags=["Materiais"])


def _obter_material_ou_404(db: Session, material_id: str) -> Material:
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material não encontrado.",
        )
    return material


def _verificar_categoria_duplicada(
    db: Session, categoria: str, ignorar_id: str | None = None
) -> None:
    query = db.query(Material).filter(
        func.lower(Material.categoria) == categoria.lower()
    )
    if ignorar_id:
        query = query.filter(Material.id != ignorar_id)
    if query.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um material com esta categoria.",
        )


@router.post(
    "/",
    response_model=MaterialResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_superuser)],
)
def criar_material(
    material_in: MaterialCreate, db: Annotated[Session, Depends(get_db)]
):
    """
    Cria um novo material e o seu respetivo fator de emissão IPCC.
    Restrito à Prefeitura (Superusuário).
    """
    _verificar_categoria_duplicada(db, material_in.categoria)

    novo_material = Material(**material_in.model_dump())

    db.add(novo_material)
    db.commit()
    db.refresh(novo_material)

    return novo_material


@router.get(
    "/",
    response_model=list[MaterialResponse],
    dependencies=[Depends(get_current_user)],
)
def listar_materiais(db: Annotated[Session, Depends(get_db)]):
    """
    Lista todos os materiais cadastrados.
    Utilizado pela aplicação móvel para popular as listas de seleção (dropdowns).
    """
    return db.query(Material).order_by(Material.categoria).all()


@router.get(
    "/{material_id}",
    response_model=MaterialResponse,
    dependencies=[Depends(get_current_user)],
)
def obter_material(material_id: str, db: Annotated[Session, Depends(get_db)]):
    """
    Obtém os detalhes de um material específico pelo ID.
    """
    return _obter_material_ou_404(db, material_id)


@router.patch(
    "/{material_id}",
    response_model=MaterialResponse,
    dependencies=[Depends(require_superuser)],
)
@router.put(
    "/{material_id}",
    response_model=MaterialResponse,
    dependencies=[Depends(require_superuser)],
    include_in_schema=False,
)
def atualizar_material(
    material_id: str,
    dados: MaterialUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Atualiza a categoria e/ou o fator de emissão IPCC de um material existente.
    Restrito à Prefeitura (Superusuário).
    """
    material = _obter_material_ou_404(db, material_id)
    alteracoes = dados.model_dump(exclude_unset=True)

    if "categoria" in alteracoes and alteracoes["categoria"] is not None:
        _verificar_categoria_duplicada(
            db, alteracoes["categoria"], ignorar_id=material_id
        )
        material.categoria = alteracoes["categoria"]

    if (
        "fator_emissaoipcc" in alteracoes
        and alteracoes["fator_emissaoipcc"] is not None
    ):
        material.fator_emissaoipcc = alteracoes["fator_emissaoipcc"]

    db.commit()
    db.refresh(material)
    return material


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_superuser)],
)
def excluir_material(material_id: str, db: Annotated[Session, Depends(get_db)]):
    """
    Remove um material cadastrado caso não possua registros vinculados.
    Restrito à Prefeitura (Superusuário).
    """
    material = _obter_material_ou_404(db, material_id)

    possui_registros = (
        db.query(Registro.id).filter(Registro.material_id == material_id).first()
        is not None
    )
    if possui_registros:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Não é possível excluir um material que possui registros vinculados."
            ),
        )

    db.delete(material)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
