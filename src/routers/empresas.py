from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.models import Empresa
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import EmpresaCreate, EmpresaResponse

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
    empresa_email = getattr(empresa_in, "email", None)
    filtros_existencia = [Empresa.cnpj == empresa_in.cnpj]
    if empresa_email is not None:
        filtros_existencia.append(Empresa.email == empresa_email)

    empresa_existente = db.query(Empresa).filter(*filtros_existencia).first()

    if empresa_existente:
        raise HTTPException(status_code=400, detail="CNPJ ou E-mail já registados.")

    pwd_hash = f"hashed_{empresa_in.senha}"

    nova_empresa = Empresa(
        prefeitura_id=empresa_in.prefeitura_id,
        nome=empresa_in.nome,
        cnpj=empresa_in.cnpj,
        razao_social=empresa_in.razao_social,
        nome_fantasia=empresa_in.nome_fantasia,
        email=empresa_email,
        telefone=empresa_in.telefone,
        endereco=empresa_in.endereco,
        pwd_hash=pwd_hash,
        empresa_status=StatusVinculo.AGUARDANDO_VALIDACAO,
    )

    db.add(nova_empresa)
    db.commit()
    db.refresh(nova_empresa)

    return nova_empresa


@router.patch("/{empresa_id}/status", response_model=EmpresaResponse)
def validar_vinculo_empresa(
    empresa_id: str,
    dados_status: AtualizarStatusEmpresa,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Endpoint para o Gestor de Resíduos aprovar ou recusar o vínculo
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
