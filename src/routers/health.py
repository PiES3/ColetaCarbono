import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from src.core.base import Base
from src.core.database import get_db
from src.schemas.schemas import (
    ComponenteBancoSaude,
    HealthLiveResponse,
    HealthStatusResponse,
)

SERVICO_NOME = "ColetaCarbono"
SERVICO_VERSAO = "0.1.0"
_INICIO_PROCESSO = time.monotonic()

router = APIRouter(tags=["Saúde do Sistema"])


def _uptime_segundos() -> float:
    return round(max(0.0, time.monotonic() - _INICIO_PROCESSO), 3)


def _diagnosticar_banco(db: Session) -> ComponenteBancoSaude:
    inicio = time.perf_counter()
    bind = db.get_bind()
    dialeto = bind.dialect.name if bind is not None else "desconhecido"

    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        latencia = round((time.perf_counter() - inicio) * 1000.0, 2)
        return ComponenteBancoSaude(
            status="error",
            dialeto=dialeto,
            conectado=False,
            schema_integro=False,
            latencia_ms=latencia,
            detalhe=f"Falha de conexão com o banco de dados: {exc}",
        )

    try:
        inspetor = inspect(bind)
        existentes = set(inspetor.get_table_names())
        esperadas = {t.name for t in Base.metadata.sorted_tables}
        ausentes = sorted(esperadas - existentes)
    except Exception as exc:
        latencia = round((time.perf_counter() - inicio) * 1000.0, 2)
        return ComponenteBancoSaude(
            status="error",
            dialeto=dialeto,
            conectado=True,
            schema_integro=False,
            latencia_ms=latencia,
            detalhe=f"Falha ao inspecionar schema: {exc}",
        )

    latencia = round((time.perf_counter() - inicio) * 1000.0, 2)
    if ausentes:
        return ComponenteBancoSaude(
            status="degraded",
            dialeto=dialeto,
            conectado=True,
            schema_integro=False,
            latencia_ms=latencia,
            detalhe=f"Tabelas ausentes: {', '.join(ausentes)}",
        )

    return ComponenteBancoSaude(
        status="ok",
        dialeto=dialeto,
        conectado=True,
        schema_integro=True,
        latencia_ms=latencia,
    )


def _montar_estado_completo(db: Session, response: Response) -> HealthStatusResponse:
    banco = _diagnosticar_banco(db)
    pronto = banco.conectado and banco.schema_integro
    if not pronto:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthStatusResponse(
        status="ok" if pronto else banco.status,
        servico=SERVICO_NOME,
        versao=SERVICO_VERSAO,
        timestamp=datetime.now(UTC),
        uptime_segundos=_uptime_segundos(),
        pronto=pronto,
        banco_dados=banco,
    )


@router.get("/health")
@router.get("/health/", include_in_schema=False)
def verificar_saude_geral(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> HealthStatusResponse:
    """
    Estado consolidado de saúde da API e do banco de dados.
    Retorna HTTP 200 quando saudável ou HTTP 503 quando indisponível/degradado.
    """
    return _montar_estado_completo(db, response)


@router.get("/health/live")
@router.get("/healthz", include_in_schema=False)
def verificar_liveness() -> HealthLiveResponse:
    """
    Sonda de vivacidade (liveness) e ping leve para clientes offline-first (RNF#001).
    Não realiza I/O de banco de dados.
    """
    return HealthLiveResponse(
        status="ok",
        servico=SERVICO_NOME,
        versao=SERVICO_VERSAO,
        timestamp=datetime.now(UTC),
        uptime_segundos=_uptime_segundos(),
    )


@router.head("/health/live", include_in_schema=False)
@router.head("/health", include_in_schema=False)
def head_liveness() -> Response:
    """Ping HTTP HEAD sem corpo para detecção rápida de conectividade no mobile."""
    return Response(status_code=status.HTTP_200_OK)


@router.get("/health/ready")
@router.get("/readyz", include_in_schema=False)
def verificar_readiness(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> HealthStatusResponse:
    """
    Sonda de prontidão (readiness): valida conectividade SQL, latência e integridade
    das tabelas antes de liberar tráfego para a instância.
    """
    return _montar_estado_completo(db, response)
