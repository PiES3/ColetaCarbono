import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import requests
from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.orm import Session

from src.models.models import Empresa, Material, Registro
from src.schemas.enums import StatusValidacao, StatusVinculo

if TYPE_CHECKING:
    from src.schemas.schemas import RegistroCreate

VALOR_TONELADA_CO2_USD = 5.0
COTACAO_DOLAR_FALLBACK = 5.30
COTACAO_CACHE_SEGUNDOS = 60 * 60
URL_COTACOES_BCE = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

_cache_cotacao: dict[str, float] = {}
_trava_cotacao = threading.Lock()


def _buscar_cotacao_dolar() -> float:
    """Cotação USD→BRL derivada das taxas de referência do Banco Central Europeu."""
    resposta = requests.get(URL_COTACOES_BCE, timeout=10)
    resposta.raise_for_status()

    taxas: dict[str, float] = {}
    for no in ET.fromstring(resposta.content).iter():
        moeda = no.attrib.get("currency")
        taxa = no.attrib.get("rate")
        if moeda and taxa:
            taxas[moeda] = float(taxa)

    return round(taxas["BRL"] / taxas["USD"], 4)


def obter_cotacao_dolar(fallback: float = COTACAO_DOLAR_FALLBACK) -> float:
    """
    Retorna a cotação do dólar em reais, guardada em cache por uma hora para
    não fazer uma requisição externa a cada validação. Em caso de falha,
    usa a última cotação conhecida ou o valor de fallback.
    """
    with _trava_cotacao:
        agora = time.monotonic()
        if agora - _cache_cotacao.get("obtida_em", float("-inf")) < (
            COTACAO_CACHE_SEGUNDOS
        ):
            return _cache_cotacao["valor"]

        try:
            valor = _buscar_cotacao_dolar()
        except (requests.RequestException, ET.ParseError, KeyError, ValueError) as erro:
            logger.warning(f"Erro ao obter cotação do dólar: {erro}")
            return _cache_cotacao.get("valor", fallback)

        _cache_cotacao.update(valor=valor, obtida_em=agora)
        return valor


class RegistroService:
    def validar_e_calcular(
        self,
        db: Session,
        registro_id: str,
        validador_id: str | None = None,
        volume_validado: float | None = None,
        prefeitura_id: str | None = None,
    ) -> Registro:
        registro = db.query(Registro).filter(Registro.id == registro_id).first()
        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registro não encontrado",
            )

        if prefeitura_id:
            empresa = registro.empresa or (
                db.query(Empresa).filter(Empresa.id == registro.empresa_id).first()
            )
            if empresa and empresa.prefeitura_id != prefeitura_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Registro não encontrado",
                )

        if registro.status_validacao != StatusValidacao.PENDENTE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registro já processado",
            )

        material = registro.material or (
            db.query(Material).filter(Material.id == registro.material_id).first()
        )
        if not material:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Material não encontrado",
            )

        if volume_validado is None:
            volume_validado = registro.volume_total_original

        if volume_validado < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Volume validado não pode ser negativo.",
            )

        carbono_evitado = (
            volume_validado
            * (registro.percentual_reciclado / 100)
            * material.fator_emissaoipcc
        )
        valor_estimado_brl = (
            carbono_evitado * VALOR_TONELADA_CO2_USD * obter_cotacao_dolar()
        )

        registro.validador_id = validador_id
        registro.volume_validado = volume_validado
        registro.status_validacao = StatusValidacao.VALIDADO
        registro.motivo_rejeicao = None
        registro.data_validacao = datetime.now(UTC)
        registro.carbonoevitado = carbono_evitado
        registro.valorestimado = round(valor_estimado_brl, 2)

        db.commit()
        db.refresh(registro)

        return registro

    def rejeitar_registro(
        self,
        db: Session,
        registro_id: str,
        motivo_rejeicao: str | None,
        validador_id: str | None = None,
        prefeitura_id: str | None = None,
    ) -> Registro:
        registro = db.query(Registro).filter(Registro.id == registro_id).first()
        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registro não encontrado",
            )

        if registro.status_validacao != StatusValidacao.PENDENTE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registro já processado",
            )

        if prefeitura_id:
            empresa = registro.empresa or (
                db.query(Empresa).filter(Empresa.id == registro.empresa_id).first()
            )
            if empresa and empresa.prefeitura_id != prefeitura_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A empresa selecionada não está vinculada à sua prefeitura.",
                )

        if not motivo_rejeicao or not motivo_rejeicao.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O motivo da rejeição é obrigatório.",
            )

        registro.validador_id = validador_id
        registro.status_validacao = StatusValidacao.REJEITADO
        registro.motivo_rejeicao = motivo_rejeicao.strip()
        registro.data_validacao = None
        registro.volume_validado = None
        registro.carbonoevitado = None
        registro.valorestimado = None

        db.commit()
        db.refresh(registro)

        return registro

    rejeitar = rejeitar_registro

    def criar_registro_gestor(
        self,
        db: Session,
        dados: RegistroCreate,
        gestor_id: str,
        prefeitura_id: str,
    ) -> Registro:
        empresa = db.query(Empresa).filter(Empresa.id == dados.empresa_id).first()
        if not empresa:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Empresa não encontrada.",
            )

        if empresa.prefeitura_id != prefeitura_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A empresa selecionada não está vinculada à sua prefeitura.",
            )

        if empresa.empresa_status != StatusVinculo.APROVADA:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "A empresa selecionada não possui vínculo aprovado "
                    "com a prefeitura."
                ),
            )

        material = db.query(Material).filter(Material.id == dados.material_id).first()
        if not material:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Material não encontrado.",
            )

        volume_validado = (
            dados.volume_validado
            if getattr(dados, "volume_validado", None) is not None
            else dados.volume_total
        )

        carbono_evitado = (
            volume_validado
            * (dados.percentual_reciclado / 100)
            * material.fator_emissaoipcc
        )
        valor_estimado_brl = (
            carbono_evitado * VALOR_TONELADA_CO2_USD * obter_cotacao_dolar()
        )

        novo_registro = Registro(
            empresa_id=dados.empresa_id,
            material_id=dados.material_id,
            periodo=dados.periodo,
            volume_total_original=dados.volume_total,
            percentual_reciclado=dados.percentual_reciclado,
            volume_validado=volume_validado,
            status_validacao=StatusValidacao.VALIDADO,
            criado_por_gestor_id=gestor_id,
            validador_id=gestor_id,
            data_validacao=datetime.now(UTC),
            carbonoevitado=carbono_evitado,
            valorestimado=round(valor_estimado_brl, 2),
        )

        db.add(novo_registro)
        db.commit()
        db.refresh(novo_registro)

        return novo_registro


registro_service = RegistroService()
