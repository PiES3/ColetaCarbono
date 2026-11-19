from fastapi import APIRouter

from src.schemas.schemas import CotacaoResponse
from src.services.services import VALOR_TONELADA_CO2_USD, obter_cotacao_dolar

router = APIRouter(prefix="/cotacao", tags=["Cotação"])


@router.get("/", response_model=CotacaoResponse)
def obter_cotacao():
    """
    Retorna a cotação do dólar usada nas estimativas financeiras e o valor da
    tonelada de CO₂ evitada em dólar e em reais. O aplicativo guarda esses
    valores para calcular a estimativa mesmo sem conexão.
    """
    dolar = obter_cotacao_dolar()
    return CotacaoResponse(
        dolar=dolar,
        valor_tonelada_usd=VALOR_TONELADA_CO2_USD,
        valor_tonelada_brl=round(VALOR_TONELADA_CO2_USD * dolar, 4),
    )
