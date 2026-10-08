import xml.etree.ElementTree as ET

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.models.models import Empresa, Material, Registro
from src.schemas.enums import StatusValidacao

VALOR_TONELADA_CO2_USD = 5.0


def obter_cotacao_dolar(fallback: float = 5.30) -> float:
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        taxas: dict[str, float] = {}

        for node in root.iter():
            currency = node.attrib.get("currency")
            rate = node.attrib.get("rate")
            if currency and rate:
                taxas[currency] = float(rate)

        eur_usd = taxas["USD"]
        eur_brl = taxas["BRL"]

        return round(eur_brl / eur_usd, 4)

    except Exception as exc:
        print(f"Erro ao obter cotação: {exc}")
        return fallback


class RegistroService:
    def validar_e_calcular(
        self,
        db: Session,
        registro_id: str,
        validador_id: str,
        volume_validado: float,
        prefeitura_id: str,
    ) -> Registro:

        registro = (
            db.query(Registro)
            .join(Registro.empresa)
            .filter(Registro.id == registro_id, Empresa.prefeitura_id == prefeitura_id)
            .first()
        )
        if not registro:
            raise HTTPException(status_code=404, detail="Registro não encontrado")

        if registro.status_validacao != StatusValidacao.PENDENTE:
            raise HTTPException(status_code=400, detail="Registro já processado")

        material = (
            db.query(Material).filter(Material.id == registro.material_id).first()
        )
        if not material:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        carbono_evitado = (
            volume_validado
            * (registro.percentual_reciclado / 100)
            * material.fator_emissaoipcc
        )

        cotacao_atual = obter_cotacao_dolar()
        valor_estimado_brl = carbono_evitado * VALOR_TONELADA_CO2_USD * cotacao_atual

        registro.validador_id = validador_id
        registro.volume_validado = volume_validado
        registro.status_validacao = StatusValidacao.VALIDADO
        registro.carbonoevitado = carbono_evitado
        registro.valorestimado = round(valor_estimado_brl, 2)

        db.commit()
        db.refresh(registro)

        return registro


registro_service = RegistroService()
