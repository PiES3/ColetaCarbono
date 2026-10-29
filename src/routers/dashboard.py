from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import get_current_user
from src.schemas.schemas import DashboardResumoResponse
from src.services.estatisticas_service import estatisticas_service

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
    Retorna todos os indicadores consolidados para o dashboard:
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
