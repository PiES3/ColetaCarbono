from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import get_current_user
from src.schemas.enums import AgrupamentoRelatorio
from src.schemas.schemas import (
    DashboardResumoResponse,
    EvolucaoTemporalResponse,
    RelatorioConsolidadoResponse,
)
from src.services.estatisticas_service import estatisticas_service
from src.services.pdf_service import gerar_pdf_relatorio

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/", response_model=DashboardResumoResponse)
@router.get("/resumo", response_model=DashboardResumoResponse, include_in_schema=False)
def obter_resumo_dashboard(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
    empresa_id: str | None = None,
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
    material_id: str | None = None,
):
    """
    Retorna todos os indicadores consolidados para o dashboard (RF#011):
    - Para a Prefeitura: contagem de empresas por status, resumo geral dos
      registros do município, séries por material e por período (AAAA-MM) e
      ranking das empresas com maior impacto ambiental.
    - Para a Empresa: resumo dos próprios registros, detalhamento por material
      e evolução por período.
    """
    return estatisticas_service.dashboard_completo(
        db=db,
        usuario=usuario,
        empresa_id=empresa_id,
        periodo=periodo,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        material_id=material_id,
    )


@router.get("/evolucao-temporal", response_model=EvolucaoTemporalResponse)
def obter_evolucao_temporal_dashboard(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
    dias: Annotated[int, Query(ge=1, le=365)] = 28,
    empresa_id: str | None = None,
    material_id: str | None = None,
):
    """
    Apresenta a série diária contínua dos últimos `dias` (padrão: 28 dias) e
    a variação percentual frente à janela anterior para análise de tendências
    da coleta seletiva em tempo real (RF#015).
    """
    return estatisticas_service.evolucao_temporal(
        db=db,
        usuario=usuario,
        dias=dias,
        empresa_id=empresa_id,
        material_id=material_id,
    )


@router.get(
    "/relatorio",
    response_model=RelatorioConsolidadoResponse,
    include_in_schema=False,
)
def obter_relatorio_via_dashboard(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
    agrupamento: AgrupamentoRelatorio = AgrupamentoRelatorio.MENSAL,
    empresa_id: str | None = None,
    material_id: str | None = None,
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
):
    return estatisticas_service.relatorio_consolidado(
        db=db,
        usuario=usuario,
        agrupamento=agrupamento,
        empresa_id=empresa_id,
        material_id=material_id,
        periodo=periodo,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
    )


@router.get("/relatorio.pdf", response_class=Response, include_in_schema=False)
def exportar_pdf_via_dashboard(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
    agrupamento: AgrupamentoRelatorio = AgrupamentoRelatorio.MENSAL,
    empresa_id: str | None = None,
    material_id: str | None = None,
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
):
    relatorio = estatisticas_service.relatorio_consolidado(
        db=db,
        usuario=usuario,
        agrupamento=agrupamento,
        empresa_id=empresa_id,
        material_id=material_id,
        periodo=periodo,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
    )
    return Response(
        content=gerar_pdf_relatorio(relatorio),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="relatorio_carbono_{agrupamento.value}.pdf"'
            )
        },
    )
