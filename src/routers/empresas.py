from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import require_empresa, require_superuser
from src.models.models import Empresa
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import (
    EmpresaCreate,
    EmpresaResponse,
    EmpresaUpdate,
    HistoricoCadastroResponse,
)
from src.services.auth_service import auth_service
from src.services.empresa_service import empresa_service

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


def empresa_do_usuario(db: Session, usuario: dict[str, Any]) -> Empresa:
    empresa = db.query(Empresa).filter(Empresa.id == usuario["empresa_id"]).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    return empresa


@router.get("/me", response_model=EmpresaResponse)
def obter_dados_da_empresa(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_empresa)],
):
    """
    Retorna os dados cadastrais da empresa autenticada (HU006).
    """
    return empresa_do_usuario(db, usuario)


@router.patch("/me", response_model=EmpresaResponse)
def editar_dados_da_empresa(
    dados_atualizacao: EmpresaUpdate,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_empresa)],
):
    """
    Edita os dados cadastrais da empresa autenticada (HU006).
    O novo e-mail só passa a valer depois de confirmado pelo link enviado a ele,
    e o CNPJ não pode ser alterado depois da validação do cadastro.
    """
    return empresa_service.atualizar_dados(
        db=db,
        empresa=empresa_do_usuario(db, usuario),
        dados=dados_atualizacao,
        autor_id=usuario["id"],
        autor_nome=usuario["nome"],
    )


@router.get("/me/historico", response_model=list[HistoricoCadastroResponse])
def historico_da_empresa(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_empresa)],
):
    """
    Lista as alterações do cadastro da empresa autenticada, da mais recente
    para a mais antiga, com autor e data/hora (HU006).
    """
    return empresa_service.listar_historico(db, usuario["empresa_id"])


@router.patch("/{empresa_id}", response_model=EmpresaResponse)
def editar_empresa(
    empresa_id: str,
    dados_atualizacao: EmpresaUpdate,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
):
    """
    Edita os dados de uma empresa existente.
    Garante que o Gestor só edite empresas do seu próprio município.
    Segue as mesmas regras e registra o histórico como a edição feita pela empresa.
    """
    empresa = (
        db.query(Empresa)
        .filter(
            Empresa.id == empresa_id,
            Empresa.prefeitura_id == usuario["prefeitura_id"],
        )
        .first()
    )

    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")

    return empresa_service.atualizar_dados(
        db=db,
        empresa=empresa,
        dados=dados_atualizacao,
        autor_id=usuario["id"],
        autor_nome=usuario["nome"],
    )


@router.get("/estatisticas/status")
def estatisticas_empresas_por_status(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
):
    """
    Retorna a contagem de empresas agrupadas por status.
    Útil para os cards do dashboard da prefeitura.
    """
    resultados = (
        db.query(Empresa.empresa_status, func.count(Empresa.id))
        .filter(
            Empresa.prefeitura_id == usuario["prefeitura_id"],
        )
        .group_by(Empresa.empresa_status)
        .all()
    )

    estatisticas = {
        status.value if hasattr(status, "value") else status: total
        for status, total in resultados
    }

    return estatisticas


@router.get("/", response_model=list[EmpresaResponse])
def listar_empresas_vinculadas(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
    empresa_status: StatusVinculo | None = None,
):
    """
    Lista as empresas vinculadas ao município da prefeitura autenticada (HU008).
    Pode ser filtrado por empresa_status.
    """
    query = db.query(Empresa).filter(Empresa.prefeitura_id == usuario["prefeitura_id"])
    if empresa_status:
        query = query.filter(Empresa.empresa_status == empresa_status)
    return query.order_by(Empresa.created_at.desc()).all()


@router.patch("/{empresa_id}/status", response_model=EmpresaResponse)
def validar_vinculo_empresa(
    empresa_id: str,
    dados_status: AtualizarStatusEmpresa,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
):
    """
    Endpoint para o Gestor da prefeitura aprovar ou recusar o vínculo
    de uma empresa do seu município (HU003).
    Se for recusada, o motivo passa a ser obrigatório.
    """
    empresa = (
        db.query(Empresa)
        .filter(
            Empresa.id == empresa_id,
            Empresa.prefeitura_id == usuario["prefeitura_id"],
        )
        .first()
    )
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")

    if (
        dados_status.novo_status == StatusVinculo.APROVADA
        and not empresa.email_confirmado
    ):
        raise HTTPException(
            status_code=400, detail="A empresa ainda não confirmou o e-mail."
        )

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
