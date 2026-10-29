from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
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
    EstatisticaEmpresaItem,
    HistoricoCadastroResponse,
)
from src.schemas.validacao import validar_motivo_recusa
from src.services.auth_service import auth_service
from src.services.empresa_service import empresa_service
from src.services.estatisticas_service import estatisticas_service

router = APIRouter(prefix="/empresas", tags=["Empresas"])


class AtualizarStatusEmpresa(BaseModel):
    novo_status: StatusVinculo
    motivo_recusa: str | None = None

    @field_validator("motivo_recusa")
    @classmethod
    def checar_motivo_recusa(cls, valor: str | None) -> str | None:
        return validar_motivo_recusa(valor)


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
    empresa = db.get(Empresa, usuario["empresa_id"])
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada."
        )
    return empresa


def empresa_do_municipio(
    db: Session, empresa_id: str, usuario: dict[str, Any]
) -> Empresa:
    """Busca a empresa garantindo que pertence ao município do gestor."""
    empresa = (
        db.query(Empresa)
        .filter(
            Empresa.id == empresa_id,
            Empresa.prefeitura_id == usuario["prefeitura_id"],
        )
        .first()
    )
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada."
        )
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


@router.get("/estatisticas/ranking", response_model=list[EstatisticaEmpresaItem])
def ranking_empresas_por_impacto(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
    material_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """
    Retorna o ranking das empresas do município ordenadas por carbono evitado
    e volume validado, útil para gráficos e tabelas do dashboard da prefeitura.
    """
    return estatisticas_service.ranking_empresas(
        db=db,
        prefeitura_id=usuario["prefeitura_id"],
        periodo=periodo,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        material_id=material_id,
        limit=limit,
    )


@router.get("/estatisticas/status")
def estatisticas_empresas_por_status(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
) -> dict[str, int]:
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

    return {str(status_vinculo): total for status_vinculo, total in resultados}


@router.get("/vinculadas", response_model=list[EmpresaResponse])
def listar_empresas_vinculadas(
    current_user: Annotated[dict[str, Any], Depends(require_superuser)],
    db: Annotated[Session, Depends(get_db)],
    status_vinculo: StatusVinculo | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
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


@router.get("/", response_model=list[EmpresaResponse])
def listar_empresas(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
    empresa_status: StatusVinculo | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """
    Lista as empresas vinculadas ao município da prefeitura autenticada (HU008).
    Pode ser filtrado por empresa_status.
    """
    query = db.query(Empresa).filter(Empresa.prefeitura_id == usuario["prefeitura_id"])
    if empresa_status:
        query = query.filter(Empresa.empresa_status == empresa_status)
    return query.order_by(Empresa.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{empresa_id}", response_model=EmpresaResponse)
def obter_empresa(
    empresa_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Obtém uma empresa pelo ID.
    """
    empresa = db.get(Empresa, empresa_id)
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada."
        )
    return empresa


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
    return empresa_service.atualizar_dados(
        db=db,
        empresa=empresa_do_municipio(db, empresa_id, usuario),
        dados=dados_atualizacao,
        autor_id=usuario["id"],
        autor_nome=usuario["nome"],
    )


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
    empresa = empresa_do_municipio(db, empresa_id, usuario)
    novo_status = dados_status.novo_status

    if novo_status == StatusVinculo.APROVADA and not empresa.email_confirmado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A empresa ainda não confirmou o e-mail.",
        )

    if novo_status == StatusVinculo.RECUSADA and not dados_status.motivo_recusa:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O motivo da recusa é obrigatório.",
        )

    empresa.empresa_status = novo_status
    # O motivo só faz sentido enquanto a empresa estiver recusada; ao aprovar
    # depois de uma recusa, o motivo antigo não deve continuar aparecendo.
    empresa.motivo_recusa = (
        dados_status.motivo_recusa if novo_status == StatusVinculo.RECUSADA else None
    )

    db.commit()
    db.refresh(empresa)

    return empresa
