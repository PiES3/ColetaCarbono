from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import get_current_user, require_superuser
from src.models.models import Material, Registro
from src.schemas.schemas import MaterialCreate, MaterialResponse, MaterialUpdate
from src.services.material_service import materiais_visiveis, material_disponivel

router = APIRouter(prefix="/materiais", tags=["Materiais"])


def _obter_material_ou_404(
    db: Session, material_id: str, usuario: dict[str, Any]
) -> Material:
    material = material_disponivel(db, material_id, usuario.get("prefeitura_id"))
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material não encontrado.",
        )
    return material


def _material_da_prefeitura(
    db: Session, material_id: str, usuario: dict[str, Any]
) -> Material:
    material = _obter_material_ou_404(db, material_id, usuario)
    if material.prefeitura_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Os materiais da lista IPCC não podem ser alterados nem excluídos.",
        )
    return material


def _verificar_categoria_duplicada(
    db: Session,
    categoria: str,
    prefeitura_id: str,
    ignorar_id: str | None = None,
) -> None:
    query = materiais_visiveis(db, prefeitura_id).filter(
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
)
def criar_material(
    material_in: MaterialCreate,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
):
    """
    Cria um novo material e o seu respetivo fator de emissão, visível apenas
    para o município da prefeitura que o cadastrou.
    Restrito à Prefeitura (Superusuário).
    """
    _verificar_categoria_duplicada(db, material_in.categoria, usuario["prefeitura_id"])

    novo_material = Material(
        **material_in.model_dump(), prefeitura_id=usuario["prefeitura_id"]
    )

    db.add(novo_material)
    db.commit()
    db.refresh(novo_material)

    return novo_material


@router.get("/", response_model=list[MaterialResponse])
def listar_materiais(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
):
    """
    Lista os materiais da lista IPCC e os cadastrados pela prefeitura do
    usuário. Utilizado pela aplicação móvel para popular as listas de seleção.
    """
    return (
        materiais_visiveis(db, usuario.get("prefeitura_id"))
        .order_by(Material.categoria)
        .all()
    )


@router.get("/{material_id}", response_model=MaterialResponse)
def obter_material(
    material_id: str,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
):
    """
    Obtém os detalhes de um material específico pelo ID.
    """
    return _obter_material_ou_404(db, material_id, usuario)


@router.patch("/{material_id}", response_model=MaterialResponse)
@router.put("/{material_id}", response_model=MaterialResponse, include_in_schema=False)
def atualizar_material(
    material_id: str,
    dados: MaterialUpdate,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
):
    """
    Atualiza a categoria e/ou o fator de emissão de um material cadastrado
    pela prefeitura. Os materiais da lista IPCC não podem ser alterados.
    Restrito à Prefeitura (Superusuário).
    """
    material = _material_da_prefeitura(db, material_id, usuario)
    alteracoes = dados.model_dump(exclude_unset=True)

    if "categoria" in alteracoes and alteracoes["categoria"] is not None:
        _verificar_categoria_duplicada(
            db,
            alteracoes["categoria"],
            usuario["prefeitura_id"],
            ignorar_id=material_id,
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


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_material(
    material_id: str,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
):
    """
    Remove um material cadastrado pela prefeitura caso não possua registros
    vinculados. Os materiais da lista IPCC não podem ser excluídos.
    Restrito à Prefeitura (Superusuário).
    """
    material = _material_da_prefeitura(db, material_id, usuario)

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
