import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import requests
from fastapi import HTTPException, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.core.security import require_empresa
from src.models.models import Empresa, HistoricoRegistro, Material, Registro
from src.schemas.enums import AcaoHistoricoRegistro, StatusValidacao, StatusVinculo
from src.services.email_service import email_service
from src.services.material_service import materiais_visiveis, material_disponivel

if TYPE_CHECKING:
    from src.schemas.schemas import (
        RegistroCreate,
        RegistroUpdate,
        SincronizacaoLoteResponse,
    )

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


def _numero(valor: float) -> str:
    return format(valor, "g")


def _resumo_registro(registro: Registro) -> str:
    categoria = registro.material.categoria if registro.material else None
    return (
        f"{categoria or registro.material_id} · {registro.periodo} · "
        f"{_numero(registro.volume_total_original)} t · "
        f"{_numero(registro.percentual_reciclado)} %"
    )


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

        if registro.correcao_solicitada:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O lançamento está aguardando a correção da empresa.",
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
        self._encerrar_pedido_correcao(registro)

        db.commit()
        db.refresh(registro)

        return registro

    rejeitar = rejeitar_registro

    def _encerrar_pedido_correcao(self, registro: Registro) -> None:
        registro.correcao_solicitada = False
        registro.motivo_correcao = None
        registro.data_solicitacao_correcao = None

    def solicitar_correcao(
        self,
        db: Session,
        registro_id: str,
        motivo_correcao: str | None,
        autor_id: str,
        autor_nome: str,
        prefeitura_id: str,
    ) -> Registro:
        """
        Devolve um lançamento pendente para a empresa corrigir, com a
        justificativa da prefeitura. O lançamento sai da fila de validação até
        a empresa salvar a correção, e a empresa é avisada por e-mail.
        """
        registro = (
            db.query(Registro)
            .join(Registro.empresa)
            .filter(
                Registro.id == registro_id,
                Empresa.prefeitura_id == prefeitura_id,
            )
            .first()
        )
        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registro não encontrado",
            )

        if registro.status_validacao != StatusValidacao.PENDENTE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Só lançamentos pendentes podem ser enviados para correção.",
            )

        if registro.correcao_solicitada:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A correção deste lançamento já foi solicitada.",
            )

        if not motivo_correcao:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A justificativa da correção é obrigatória.",
            )

        registro.correcao_solicitada = True
        registro.motivo_correcao = motivo_correcao
        registro.data_solicitacao_correcao = datetime.now(UTC)
        self._registrar_alteracao(
            db=db,
            registro=registro,
            acao=AcaoHistoricoRegistro.EDICAO,
            autor_id=autor_id,
            autor_nome=autor_nome,
            campo="correcao_solicitada",
            anterior=None,
            novo=motivo_correcao,
        )

        db.commit()
        db.refresh(registro)

        empresa = registro.empresa
        email_service.enviar(
            destinatario=empresa.email,
            assunto="ArClear: a prefeitura pediu a correção de um lançamento",
            corpo=(
                f"A Prefeitura de {empresa.prefeitura.nome} pediu a correção do "
                f"lançamento {_resumo_registro(registro)}.\n\n"
                f"Justificativa: {motivo_correcao}\n\n"
                "Abra o aplicativo, corrija o lançamento e salve para enviá-lo "
                "de novo para validação."
            ),
        )

        return registro

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

        client_id = (dados.client_id or "").strip() or None
        if client_id:
            existente = (
                db.query(Registro)
                .filter(
                    Registro.empresa_id == empresa.id,
                    Registro.client_id == client_id,
                )
                .first()
            )
            if existente:
                return existente

        material = material_disponivel(db, dados.material_id, prefeitura_id)
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
            client_id=client_id,
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

    def _registro_alteravel(
        self, db: Session, registro_id: str, empresa_id: str
    ) -> Registro:
        registro = (
            db.query(Registro)
            .filter(Registro.id == registro_id, Registro.empresa_id == empresa_id)
            .first()
        )
        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registro não encontrado.",
            )
        if registro.status_validacao == StatusValidacao.VALIDADO:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lançamentos validados não podem ser editados nem excluídos.",
            )
        return registro

    def _registrar_alteracao(
        self,
        db: Session,
        registro: Registro,
        acao: AcaoHistoricoRegistro,
        autor_id: str,
        autor_nome: str,
        campo: str,
        anterior: str | None,
        novo: str | None,
    ) -> None:
        db.add(
            HistoricoRegistro(
                registro_id=registro.id,
                empresa_id=registro.empresa_id,
                autor_id=autor_id,
                autor_nome=autor_nome,
                acao=acao,
                campo=campo,
                valor_anterior=anterior,
                valor_novo=novo,
            )
        )

    def editar_registro(
        self,
        db: Session,
        registro_id: str,
        empresa_id: str,
        dados: RegistroUpdate,
        autor_id: str,
        autor_nome: str,
    ) -> Registro:
        """
        Corrige um lançamento pendente ou rejeitado da empresa (HU012).
        Cada campo alterado fica no histórico com autor e data/hora, e um
        lançamento rejeitado ou com correção solicitada volta para a fila de
        validação.
        """
        registro = self._registro_alteravel(db, registro_id, empresa_id)
        alteracoes = dados.model_dump(exclude_none=True)
        mudancas: list[tuple[str, str | None, str | None]] = []

        novo_material_id = alteracoes.get("material_id")
        if novo_material_id and novo_material_id != registro.material_id:
            material = material_disponivel(
                db, novo_material_id, registro.empresa.prefeitura_id
            )
            if not material:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Material inválido.",
                )
            anterior = registro.material.categoria if registro.material else None
            mudancas.append(
                ("material", anterior or registro.material_id, material.categoria)
            )
            registro.material_id = material.id

        novo_periodo = alteracoes.get("periodo")
        if novo_periodo and novo_periodo != registro.periodo:
            mudancas.append(("periodo", registro.periodo, novo_periodo))
            registro.periodo = novo_periodo

        novo_volume = alteracoes.get("volume_total")
        if novo_volume is not None and novo_volume != registro.volume_total_original:
            mudancas.append(
                (
                    "volume_total",
                    _numero(registro.volume_total_original),
                    _numero(novo_volume),
                )
            )
            registro.volume_total_original = novo_volume

        novo_percentual = alteracoes.get("percentual_reciclado")
        if (
            novo_percentual is not None
            and novo_percentual != registro.percentual_reciclado
        ):
            mudancas.append(
                (
                    "percentual_reciclado",
                    _numero(registro.percentual_reciclado),
                    _numero(novo_percentual),
                )
            )
            registro.percentual_reciclado = novo_percentual

        if mudancas and registro.correcao_solicitada:
            mudancas.append(("correcao_solicitada", registro.motivo_correcao, None))
            self._encerrar_pedido_correcao(registro)

        if mudancas and registro.status_validacao != StatusValidacao.PENDENTE:
            mudancas.append(
                (
                    "status_validacao",
                    StatusValidacao.REJEITADO.value,
                    StatusValidacao.PENDENTE.value,
                )
            )
            registro.status_validacao = StatusValidacao.PENDENTE
            registro.motivo_rejeicao = None
            registro.validador_id = None
            registro.data_validacao = None

        for campo, anterior, novo in mudancas:
            self._registrar_alteracao(
                db=db,
                registro=registro,
                acao=AcaoHistoricoRegistro.EDICAO,
                autor_id=autor_id,
                autor_nome=autor_nome,
                campo=campo,
                anterior=anterior,
                novo=novo,
            )

        db.commit()
        db.refresh(registro)
        return registro

    def excluir_registro(
        self,
        db: Session,
        registro_id: str,
        empresa_id: str,
        autor_id: str,
        autor_nome: str,
    ) -> None:
        """
        Exclui um lançamento pendente ou rejeitado da empresa (HU012).
        O histórico guarda um resumo do lançamento, o autor e a data/hora.
        """
        registro = self._registro_alteravel(db, registro_id, empresa_id)
        self._registrar_alteracao(
            db=db,
            registro=registro,
            acao=AcaoHistoricoRegistro.EXCLUSAO,
            autor_id=autor_id,
            autor_nome=autor_nome,
            campo="registro",
            anterior=_resumo_registro(registro),
            novo=None,
        )
        db.delete(registro)
        db.commit()

    def listar_alteracoes(
        self,
        db: Session,
        usuario: dict[str, Any],
        registro_id: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[HistoricoRegistro]:
        query = db.query(HistoricoRegistro)
        if usuario["user_type"] == "PREFEITURA":
            query = query.join(
                Empresa, HistoricoRegistro.empresa_id == Empresa.id
            ).filter(Empresa.prefeitura_id == usuario["prefeitura_id"])
        else:
            require_empresa(usuario)
            query = query.filter(HistoricoRegistro.empresa_id == usuario["empresa_id"])

        if registro_id:
            query = query.filter(HistoricoRegistro.registro_id == registro_id)

        return (
            query.order_by(HistoricoRegistro.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def sincronizar_lote(
        self,
        db: Session,
        empresa_id: str,
        prefeitura_id: str,
        brutos: list[dict[str, Any]],
    ) -> SincronizacaoLoteResponse:
        """
        Sincroniza em lote registros coletados offline pelo app móvel (RNF#001).
        Garante idempotência via `client_id`: reenviar o mesmo lote por falha de
        conexão devolve o registro já existente em vez de duplicá-lo. Cada item
        é validado separadamente, e um item inválido não impede os demais.
        """
        from src.schemas.schemas import (
            ErroSincronizacaoItem,
            RegistroCreate,
            RegistroResponse,
            SincronizacaoLoteResponse,
        )

        erros: list[ErroSincronizacaoItem] = []
        itens: list[tuple[int, RegistroCreate]] = []
        for indice, bruto in enumerate(brutos):
            try:
                itens.append((indice, RegistroCreate.model_validate(bruto)))
            except ValidationError as erro:
                cid = bruto.get("client_id")
                erros.append(
                    ErroSincronizacaoItem(
                        indice=indice,
                        client_id=cid.strip() if isinstance(cid, str) else None,
                        erro=erro.errors()[0]["msg"],
                    )
                )

        ids_materiais = {item.material_id for _, item in itens}
        materiais_validos = {
            m.id
            for m in materiais_visiveis(db, prefeitura_id)
            .filter(Material.id.in_(ids_materiais))
            .all()
        }

        client_ids_lote = {
            item.client_id.strip()
            for _, item in itens
            if item.client_id and item.client_id.strip()
        }
        existentes_por_client_id: dict[str, Registro] = {}
        if client_ids_lote:
            existentes = (
                db.query(Registro)
                .filter(
                    Registro.empresa_id == empresa_id,
                    Registro.client_id.in_(client_ids_lote),
                )
                .all()
            )
            existentes_por_client_id = {
                reg.client_id: reg for reg in existentes if reg.client_id
            }

        criados: list[Registro] = []
        resultado_ordenado: list[Registro] = []
        total_duplicados = 0

        for indice, item in itens:
            cid = item.client_id.strip() if item.client_id else None
            cid = cid or None

            if cid and cid in existentes_por_client_id:
                total_duplicados += 1
                resultado_ordenado.append(existentes_por_client_id[cid])
                continue

            if item.material_id not in materiais_validos:
                erros.append(
                    ErroSincronizacaoItem(
                        indice=indice,
                        client_id=cid,
                        erro=f"Material inválido: {item.material_id}.",
                    )
                )
                continue

            novo = Registro(
                empresa_id=empresa_id,
                material_id=item.material_id,
                client_id=cid,
                periodo=item.periodo,
                volume_total_original=item.volume_total,
                percentual_reciclado=item.percentual_reciclado,
            )
            db.add(novo)
            criados.append(novo)
            resultado_ordenado.append(novo)
            if cid:
                existentes_por_client_id[cid] = novo

        if criados:
            db.commit()
            for novo in criados:
                db.refresh(novo)

        erros.sort(key=lambda erro: erro.indice)
        return SincronizacaoLoteResponse(
            total_recebidos=len(brutos),
            total_criados=len(criados),
            total_duplicados=total_duplicados,
            total_erros=len(erros),
            registros=[
                RegistroResponse.model_validate(reg) for reg in resultado_ordenado
            ],
            erros=erros,
        )


registro_service = RegistroService()
