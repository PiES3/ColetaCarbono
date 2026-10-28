from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from src.core.database import get_db
from src.core.security import get_current_user_optional, require_superuser
from src.models.models import Registro
from src.schemas.enums import StatusValidacao
from src.schemas.schemas import (
    RegistroAcompanhamentoResponse,
    RegistroCreate,
    RegistroGestorCreate,
    RegistroRejeicaoRequest,
    RegistroResponse,
    RegistroValidacaoRequest,
    RegistroValidacaoUpdate,
)
from src.services.services import registro_service

router = APIRouter(prefix="/registros", tags=["Registros"])

ValidacaoRequest = RegistroValidacaoRequest
RejeicaoRequest = RegistroRejeicaoRequest


@router.post(
    "/gestor",
    response_model=RegistroResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Gestor da prefeitura lança registro em nome de empresa vinculada",
)
@router.post(
    "/prefeitura",
    response_model=RegistroResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def criar_registro_gestor(
    registro_in: RegistroGestorCreate,
    current_user: Annotated[dict[str, Any], Depends(require_superuser)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Permite que o gestor da prefeitura lance um registro de resíduos em nome
    de uma empresa vinculada à sua prefeitura. O registro já nasce com o
    status VALIDADO, constando o gestor como autor e validador, com cálculos
    de carbono evitado e estimativa financeira realizados.
    """
    return registro_service.criar_registro_gestor(
        db=db,
        dados=registro_in,
        gestor_id=current_user["id"],
        prefeitura_id=current_user["prefeitura_id"],
    )


@router.post("/", response_model=RegistroResponse, status_code=status.HTTP_201_CREATED)
def criar_registro(
    registro_in: RegistroCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        dict[str, Any] | None, Depends(get_current_user_optional)
    ] = None,
):
    """
    Recebe um novo registro.
    - Se enviado por um Gestor da Prefeitura autenticado, lança o registro
      em nome da empresa com status já validado.
    - Se enviado pela empresa ou sincronização móvel, cria com status PENDENTE.
    """
    if current_user and current_user.get("user_type") == "PREFEITURA":
        return registro_service.criar_registro_gestor(
            db=db,
            dados=registro_in,
            gestor_id=current_user["id"],
            prefeitura_id=current_user["prefeitura_id"],
        )

    novo_registro = Registro(
        empresa_id=registro_in.empresa_id,
        material_id=registro_in.material_id,
        periodo=registro_in.periodo,
        volume_total_original=registro_in.volume_total,
        percentual_reciclado=registro_in.percentual_reciclado,
    )

    db.add(novo_registro)
    db.commit()
    db.refresh(novo_registro)

    return novo_registro


def _normalizar_status(
    status_str: str | None, status_val: StatusValidacao | None
) -> StatusValidacao | None:
    if status_val:
        return status_val
    if not status_str:
        return None
    s = status_str.strip().upper()
    if s in ("VALIDADO", "VALIDADA"):
        return StatusValidacao.VALIDADO
    if s in ("PENDENTE", "PENDENTES"):
        return StatusValidacao.PENDENTE
    if s in ("REJEITADO", "REJEITADA", "RECUSADO", "RECUSADA"):
        return StatusValidacao.REJEITADO
    try:
        return StatusValidacao(s)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Status de validação inválido: {status_str}",
        )


@router.get(
    "/acompanhamento",
    response_model=list[RegistroAcompanhamentoResponse],
    summary="Acompanhamento da situação dos registros da empresa",
)
@router.get(
    "/empresa",
    response_model=list[RegistroAcompanhamentoResponse],
    include_in_schema=False,
)
@router.get(
    "/empresa/acompanhamento",
    response_model=list[RegistroAcompanhamentoResponse],
    include_in_schema=False,
)
def acompanhar_registros_empresa(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        dict[str, Any] | None, Depends(get_current_user_optional)
    ] = None,
    empresa_id: str | None = None,
    status_param: str | None = Query(default=None, alias="status"),
    status_validacao: StatusValidacao | None = None,
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    apenas_lancados_pela_empresa: bool | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Endpoint para a empresa acompanhar a situação de cada registro que ela lançou.
    Exibe se foi validado, pendente ou rejeitado.
    Se for rejeitado, apresenta o motivo da rejeição.
    Se for validado, apresenta a data/hora da validação e quem realizou nos registros dados como validados.
    A lista pode ser filtrada pelo status e por período de tempo.
    """
    empresa_alvo_id = empresa_id
    if current_user:
        if current_user.get("user_type") == "EMPRESA":
            empresa_alvo_id = current_user["id"]
        elif current_user.get("user_type") == "USUARIO_EMPRESA":
            empresa_alvo_id = current_user.get("empresa_id")

    if not empresa_alvo_id:
        if current_user and current_user.get("user_type") == "PREFEITURA":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="É necessário informar 'empresa_id' para consultar o acompanhamento.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária para consultar o acompanhamento dos registros da empresa.",
        )

    query = (
        db.query(Registro)
        .options(
            joinedload(Registro.criador_gestor),
            joinedload(Registro.validador),
        )
        .filter(Registro.empresa_id == empresa_alvo_id)
    )

    status_filtro = _normalizar_status(status_param, status_validacao)
    if status_filtro:
        query = query.filter(Registro.status_validacao == status_filtro)

    if periodo:
        query = query.filter(Registro.periodo == periodo)
    if periodo_inicio:
        query = query.filter(Registro.periodo >= periodo_inicio)
    if periodo_fim:
        query = query.filter(Registro.periodo <= periodo_fim)
    if data_inicio:
        try:
            d_ini = datetime.fromisoformat(data_inicio)
            query = query.filter(Registro.created_at >= d_ini)
        except Exception:
            query = query.filter(Registro.periodo >= data_inicio)
    if data_fim:
        try:
            d_fim = datetime.fromisoformat(data_fim)
            query = query.filter(Registro.created_at <= d_fim)
        except Exception:
            query = query.filter(Registro.periodo <= data_fim)

    if apenas_lancados_pela_empresa is True:
        query = query.filter(Registro.criado_por_gestor_id.is_(None))
    elif apenas_lancados_pela_empresa is False:
        query = query.filter(Registro.criado_por_gestor_id.isnot(None))

    registros = (
        query.order_by(Registro.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return registros


@router.get("/", response_model=list[RegistroResponse])
def listar_registros(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        dict[str, Any] | None, Depends(get_current_user_optional)
    ] = None,
    empresa_id: str | None = None,
    status_param: str | None = Query(default=None, alias="status"),
    status_validacao: StatusValidacao | None = None,
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    apenas_prefeitura: bool | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Lista os registros, do mais recente para o mais antigo.
    Pode ser filtrado por:
    - empresa_id (histórico da empresa)
    - status / status_validacao (fila do gestor / situação)
    - periodo / período de tempo
    - apenas_prefeitura (filtrar lançamentos feitos pela prefeitura)
    A empresa visualiza se o registro foi inserido pela prefeitura
    através do campo 'inserido_pela_prefeitura' e 'origem'.
    """
    if current_user and current_user.get("user_type") == "EMPRESA" and not empresa_id:
        empresa_id = current_user["id"]
    elif (
        current_user
        and current_user.get("user_type") == "USUARIO_EMPRESA"
        and not empresa_id
    ):
        empresa_id = current_user.get("empresa_id")

    query = db.query(Registro).options(
        joinedload(Registro.criador_gestor),
        joinedload(Registro.validador),
    )

    if empresa_id:
        query = query.filter(Registro.empresa_id == empresa_id)

    status_filtro = _normalizar_status(status_param, status_validacao)
    if status_filtro:
        query = query.filter(Registro.status_validacao == status_filtro)

    if periodo:
        query = query.filter(Registro.periodo == periodo)
    if periodo_inicio:
        query = query.filter(Registro.periodo >= periodo_inicio)
    if periodo_fim:
        query = query.filter(Registro.periodo <= periodo_fim)
    if data_inicio:
        try:
            d_ini = datetime.fromisoformat(data_inicio)
            query = query.filter(Registro.created_at >= d_ini)
        except Exception:
            query = query.filter(Registro.periodo >= data_inicio)
    if data_fim:
        try:
            d_fim = datetime.fromisoformat(data_fim)
            query = query.filter(Registro.created_at <= d_fim)
        except Exception:
            query = query.filter(Registro.periodo <= data_fim)

    if apenas_prefeitura is True:
        query = query.filter(Registro.criado_por_gestor_id.isnot(None))
    elif apenas_prefeitura is False:
        query = query.filter(Registro.criado_por_gestor_id.is_(None))

    registros = (
        query.order_by(Registro.created_at.desc()).offset(skip).limit(limit).all()
    )
    return registros


@router.get("/{registro_id}", response_model=RegistroResponse)
def obter_registro(
    registro_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Obtém os detalhes de um registro específico pelo seu ID.
    """
    registro = (
        db.query(Registro)
        .options(
            joinedload(Registro.criador_gestor),
            joinedload(Registro.validador),
        )
        .filter(Registro.id == registro_id)
        .first()
    )
    if not registro:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro não encontrado.",
        )
    return registro


@router.patch("/{registro_id}/validar", response_model=RegistroResponse)
def validar_registro(
    registro_id: str,
    dados_validacao: ValidacaoRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        dict[str, Any] | None, Depends(get_current_user_optional)
    ] = None,
):
    """
    Endpoint utilizado pelo Gestor de Resíduos da Prefeitura para validar a pesagem.
    Pode validar com o volume total original ou parcialmente.
    Executa o cálculo do carbono evitado e a estimativa financeira via RegistroService.
    """
    if current_user and (
        not current_user.get("is_superuser")
        or current_user.get("user_type") != "PREFEITURA"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito à Prefeitura (Superusuário).",
        )

    validador_id = dados_validacao.validador_id or (
        current_user["id"] if current_user else None
    )

    registro_atualizado = registro_service.validar_e_calcular(
        db=db,
        registro_id=registro_id,
        validador_id=validador_id,
        volume_validado=dados_validacao.volume_validado,
        prefeitura_id=current_user.get("prefeitura_id") if current_user else None,
    )

    return registro_atualizado


@router.patch("/{registro_id}/rejeitar", response_model=RegistroResponse)
@router.post(
    "/{registro_id}/rejeitar",
    response_model=RegistroResponse,
    include_in_schema=False,
)
def rejeitar_registro(
    registro_id: str,
    dados_rejeicao: RejeicaoRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        dict[str, Any] | None, Depends(get_current_user_optional)
    ] = None,
):
    """
    Endpoint utilizado pelo Gestor de Resíduos da Prefeitura para rejeitar um registro.
    O fornecimento de um motivo para a rejeição é obrigatório.
    """
    if current_user and (
        not current_user.get("is_superuser")
        or current_user.get("user_type") != "PREFEITURA"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito à Prefeitura (Superusuário).",
        )

    validador_id = dados_rejeicao.validador_id or (
        current_user["id"] if current_user else None
    )

    registro_atualizado = registro_service.rejeitar_registro(
        db=db,
        registro_id=registro_id,
        motivo_rejeicao=dados_rejeicao.motivo_rejeicao,
        validador_id=validador_id,
        prefeitura_id=current_user.get("prefeitura_id") if current_user else None,
    )

    return registro_atualizado


@router.patch("/{registro_id}/status", response_model=RegistroResponse)
def atualizar_status_registro(
    registro_id: str,
    dados: RegistroValidacaoUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        dict[str, Any] | None, Depends(get_current_user_optional)
    ] = None,
):
    """
    Atualiza o status de validação do registro (VALIDADO ou REJEITADO).
    Se for rejeitado, o motivo é obrigatório.
    """
    if current_user and (
        not current_user.get("is_superuser")
        or current_user.get("user_type") != "PREFEITURA"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito à Prefeitura (Superusuário).",
        )

    validador_id = dados.validador_id or (
        current_user["id"] if current_user else None
    )

    if dados.status_validacao == StatusValidacao.VALIDADO:
        return registro_service.validar_e_calcular(
            db=db,
            registro_id=registro_id,
            validador_id=validador_id,
            volume_validado=dados.volume_validado,
            prefeitura_id=current_user.get("prefeitura_id") if current_user else None,
        )
    elif dados.status_validacao in (
        StatusValidacao.REJEITADO,
        StatusValidacao.RECUSADA,
    ):
        return registro_service.rejeitar_registro(
            db=db,
            registro_id=registro_id,
            motivo_rejeicao=dados.motivo_rejeicao,
            validador_id=validador_id,
            prefeitura_id=current_user.get("prefeitura_id") if current_user else None,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Status de validação inválido: {dados.status_validacao}",
        )
