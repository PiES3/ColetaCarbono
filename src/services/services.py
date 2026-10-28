from datetime import UTC, datetime
from typing import TYPE_CHECKING

import requests
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.models.models import Empresa, Material, Registro
from src.schemas.enums import StatusValidacao, StatusVinculo

if TYPE_CHECKING:
    from src.schemas.schemas import RegistroCreate

VALOR_TONELADA_CO2_USD = 5.0


def obter_cotacao_dolar() -> float:
    try:
        response = requests.get("https://economia.awesomeapi.com.br/last/USD-BRL")
        response.raise_for_status()
        dados = response.json()
        return float(dados["USDBRL"]["bid"])
    except Exception:
        return 5.30


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
            raise HTTPException(status_code=404, detail="Registro não encontrado")

        if registro.status_validacao != StatusValidacao.PENDENTE:
            raise HTTPException(status_code=400, detail="Registro já processado")

        if prefeitura_id:
            empresa = (
                db.query(Empresa).filter(Empresa.id == registro.empresa_id).first()
            )
            if empresa and empresa.prefeitura_id != prefeitura_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A empresa selecionada não está vinculada à sua prefeitura.",
                )

        material = (
            db.query(Material).filter(Material.id == registro.material_id).first()
        )
        if not material:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        if volume_validado is None:
            volume_validado = registro.volume_total_original

        if volume_validado < 0:
            raise HTTPException(
                status_code=400,
                detail="Volume validado não pode ser negativo.",
            )

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
            empresa = (
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

        cotacao_atual = obter_cotacao_dolar()
        valor_estimado_brl = carbono_evitado * VALOR_TONELADA_CO2_USD * cotacao_atual

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
