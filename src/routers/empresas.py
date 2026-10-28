from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import get_current_user_optional, require_superuser
from src.models.models import Empresa
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import EmpresaCreate, EmpresaResponse
from src.services.auth_service import auth_service

router = APIRouter(prefix="/empresas", tags=["Empresas"])


class AtualizarStatusEmpresa(BaseModel):
    novo_status: StatusVinculo
    motivo_recusa: str | None = None


@router.post("/", response_model=EmpresaResponse, status_code=status.HTTP_201_CREATED)
def autocadastro_empresa(
    empresa_in: EmpresaCreate, db: Annotated[Session, Depends(get_db)]
):
    """
    Permite que uma empresa faça o autocadastro vinculando-se a uma prefeitura (HU001).
    A empresa nasce com o status 'AGUARDANDO_VALIDACAO'.
    """
    return auth_service.register_company(db=db, dados=empresa_in)


@router.patch("/{empresa_id}/status", response_model=EmpresaResponse)
def validar_vinculo_empresa(
    empresa_id: str,
    dados_status: AtualizarStatusEmpresa,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Endpoint para o Gestor da prefeitura aprovar ou recusar o vínculo
    de uma empresa (HU003).
    Se for recusada, o motivo passa a ser obrigatório.
    """
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")

    if (
        dados_status.novo_status == StatusVinculo.RECUSADA
        and not dados_status.motivo_recusa
    ):
        raise HTTPException(status_code=400, detail="O motivo da recusa é obrigatório.")

    empresa.empresa_status = dados_status.novo_status
    if dados_status.motivo_recusa:
        empresa.motivo_recusa = dados_status.motivo_recusa

    db.commit()
    db.refresh(empresa)

    return empresa


@router.get("/", response_model=list[EmpresaResponse])
def listar_empresas(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        dict[str, Any] | None, Depends(get_current_user_optional)
    ] = None,
    prefeitura_id: str | None = None,
    empresa_status: StatusVinculo | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Lista empresas cadastradas no sistema.
    Pode ser filtrada por prefeitura_id e empresa_status.
    Se o solicitante for um Gestor da Prefeitura e prefeitura_id não for informado,
    retorna por padrão as empresas vinculadas à sua prefeitura.
    """
    query = db.query(Empresa)

    if (
        current_user
        and current_user.get("user_type") == "PREFEITURA"
        and not prefeitura_id
    ):
        prefeitura_id = current_user.get("prefeitura_id")

    if prefeitura_id:
        query = query.filter(Empresa.prefeitura_id == prefeitura_id)
    if empresa_status:
        query = query.filter(Empresa.empresa_status == empresa_status)

    return query.order_by(Empresa.razao_social.asc()).offset(skip).limit(limit).all()


@router.get("/vinculadas", response_model=list[EmpresaResponse])
def listar_empresas_vinculadas(
    current_user: Annotated[dict[str, Any], Depends(require_superuser)],
    db: Annotated[Session, Depends(get_db)],
    status_vinculo: StatusVinculo | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Endpoint para o Gestor da prefeitura listar as empresas vinculadas à sua
    prefeitura para seleção ao lançar registros.
    """
    prefeitura_id = current_user.get("prefeitura_id")
    query = db.query(Empresa).filter(Empresa.prefeitura_id == prefeitura_id)
    if status_vinculo:
        query = query.filter(Empresa.empresa_status == status_vinculo)

    return query.order_by(Empresa.razao_social.asc()).offset(skip).limit(limit).all()


@router.get("/{empresa_id}", response_model=EmpresaResponse)
def obter_empresa(
    empresa_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Obtém uma empresa pelo ID.
    """
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    return empresa
