from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import get_current_user
from src.schemas.enums import AgrupamentoRelatorio
from src.schemas.schemas import RelatorioConsolidadoResponse
from src.services.estatisticas_service import estatisticas_service
from src.services.pdf_service import gerar_pdf_relatorio

router = APIRouter(prefix="/relatorios", tags=["Relatórios"])


@router.get("/", response_model=RelatorioConsolidadoResponse)
def obter_relatorio_consolidado(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
    agrupamento: AgrupamentoRelatorio = AgrupamentoRelatorio.MENSAL,
    empresa_id: str | None = None,
    material_id: str | None = None,
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
):
    """
    Gera relatório consolidado agrupado por período (`semanal`, `mensal` ou
    `anual`) e segmentado por tipo de material (RF#013).
    """
    return estatisticas_service.relatorio_consolidado(
        db=db,
        usuario=usuario,
        agrupamento=agrupamento,
        empresa_id=empresa_id,
        material_id=material_id,
        periodo=periodo,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )


@router.get(
    "/exportar.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
@router.get("/pdf", response_class=Response, include_in_schema=False)
def exportar_relatorio_pdf(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
    agrupamento: AgrupamentoRelatorio = AgrupamentoRelatorio.MENSAL,
    empresa_id: str | None = None,
    material_id: str | None = None,
    periodo: str | None = None,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
):
    """
    Exporta o relatório consolidado em formato PDF (RF#014).
    """
    relatorio = estatisticas_service.relatorio_consolidado(
        db=db,
        usuario=usuario,
        agrupamento=agrupamento,
        empresa_id=empresa_id,
        material_id=material_id,
        periodo=periodo,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )
    conteudo_pdf = gerar_pdf_relatorio(relatorio)
    nome_arquivo = f"relatorio_carbono_{agrupamento.value}.pdf"
    return Response(
        content=conteudo_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{nome_arquivo}"',
        },
    )
