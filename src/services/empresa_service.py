from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.models.models import Empresa, HistoricoCadastro
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import (
    DecisaoDesassociacaoRequest,
    EmpresaUpdate,
    SolicitarDesassociacaoRequest,
)
from src.services.auth_service import auth_service
from src.services.email_service import email_service

CAMPOS_EDITAVEIS = ("razao_social", "nome_fantasia", "telefone", "endereco")


class EmpresaService:
    def _registrar_historico(
        self,
        db: Session,
        empresa_id: str,
        autor_id: str,
        autor_nome: str,
        campo: str,
        anterior: str | None,
        novo: str | None,
    ) -> None:
        db.add(
            HistoricoCadastro(
                empresa_id=empresa_id,
                autor_id=autor_id,
                autor_nome=autor_nome,
                campo=campo,
                valor_anterior=anterior,
                valor_novo=novo,
            )
        )

    def atualizar_dados(
        self,
        db: Session,
        empresa: Empresa,
        dados: EmpresaUpdate,
        autor_id: str,
        autor_nome: str,
    ) -> Empresa:
        """
        Atualiza os dados cadastrais da empresa (RF#005 / HU006).
        Cada campo alterado fica registrado no histórico com autor e data/hora.
        A troca de e-mail só vale depois da confirmação pelo link enviado
        ao novo endereço, e o CNPJ não muda depois da validação do cadastro.
        """
        alteracoes = dados.model_dump(exclude_unset=True)

        def registrar(campo: str, anterior: str | None, novo: str | None) -> None:
            self._registrar_historico(
                db=db,
                empresa_id=empresa.id,
                autor_id=autor_id,
                autor_nome=autor_nome,
                campo=campo,
                anterior=anterior,
                novo=novo,
            )

        novo_cnpj = alteracoes.pop("cnpj", None)
        if novo_cnpj and novo_cnpj != empresa.cnpj:
            self._validar_troca_de_cnpj(db, empresa, novo_cnpj)
            registrar("cnpj", empresa.cnpj, novo_cnpj)
            empresa.cnpj = novo_cnpj

        novo_email = alteracoes.pop("email", None)
        if novo_email and novo_email not in (empresa.email, empresa.email_pendente):
            if auth_service.email_em_uso(db, novo_email, ignorar_empresa_id=empresa.id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="E-mail já cadastrado.",
                )
            registrar("email_pendente", empresa.email_pendente, novo_email)
            empresa.email_pendente = novo_email
            auth_service.gerar_token_confirmacao(empresa, destino=novo_email)

        for campo in CAMPOS_EDITAVEIS:
            if campo not in alteracoes:
                continue
            novo = alteracoes[campo]
            if isinstance(novo, str):
                novo = novo.strip() or None
            anterior = getattr(empresa, campo)
            if novo != anterior:
                registrar(campo, anterior, novo)
                setattr(empresa, campo, novo)

        db.commit()
        db.refresh(empresa)
        return empresa

    def solicitar_desassociacao(
        self,
        db: Session,
        empresa: Empresa,
        dados: SolicitarDesassociacaoRequest,
        autor_id: str,
        autor_nome: str,
    ) -> Empresa:
        """
        Registra o pedido da empresa para se desassociar do sistema (RF#004).
        A desassociação efetiva depende de validação do gestor da prefeitura.
        """
        if empresa.empresa_status == StatusVinculo.DESASSOCIADA:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A empresa já está desassociada.",
            )
        if empresa.desassociacao_solicitada:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Já existe uma solicitação de desassociação pendente.",
            )

        empresa.desassociacao_solicitada = True
        empresa.motivo_desassociacao = dados.motivo
        empresa.data_solicitacao_desassociacao = datetime.now(UTC)

        self._registrar_historico(
            db=db,
            empresa_id=empresa.id,
            autor_id=autor_id,
            autor_nome=autor_nome,
            campo="desassociacao_solicitada",
            anterior="false",
            novo=dados.motivo or "true",
        )

        db.commit()
        db.refresh(empresa)
        return empresa

    def cancelar_solicitacao_desassociacao(
        self,
        db: Session,
        empresa: Empresa,
        autor_id: str,
        autor_nome: str,
    ) -> Empresa:
        """Permite que a empresa cancele um pedido de desassociação ainda pendente."""
        if not empresa.desassociacao_solicitada:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não há solicitação de desassociação pendente.",
            )

        anterior = empresa.motivo_desassociacao or "true"
        empresa.desassociacao_solicitada = False
        empresa.motivo_desassociacao = None
        empresa.data_solicitacao_desassociacao = None

        self._registrar_historico(
            db=db,
            empresa_id=empresa.id,
            autor_id=autor_id,
            autor_nome=autor_nome,
            campo="desassociacao_solicitada",
            anterior=anterior,
            novo="cancelada",
        )

        db.commit()
        db.refresh(empresa)
        return empresa

    def listar_solicitacoes_desassociacao(
        self, db: Session, prefeitura_id: str
    ) -> list[Empresa]:
        return (
            db.query(Empresa)
            .filter(
                Empresa.prefeitura_id == prefeitura_id,
                Empresa.desassociacao_solicitada.is_(True),
            )
            .order_by(Empresa.data_solicitacao_desassociacao.asc())
            .all()
        )

    def decidir_desassociacao(
        self,
        db: Session,
        empresa: Empresa,
        dados: DecisaoDesassociacaoRequest,
        gestor_id: str,
        gestor_nome: str,
    ) -> Empresa:
        """
        Permite ao gestor da prefeitura aprovar ou recusar a solicitação de
        desassociação da empresa (RF#004).
        """
        if not empresa.desassociacao_solicitada:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Esta empresa não possui solicitação de desassociação pendente.",
            )

        status_anterior = str(empresa.empresa_status)
        prefeitura_nome = empresa.prefeitura.nome

        if dados.aprovar:
            empresa.empresa_status = StatusVinculo.DESASSOCIADA
            empresa.desassociacao_solicitada = False
            empresa.deleted_at = datetime.now(UTC)
            self._registrar_historico(
                db=db,
                empresa_id=empresa.id,
                autor_id=gestor_id,
                autor_nome=gestor_nome,
                campo="empresa_status",
                anterior=status_anterior,
                novo=StatusVinculo.DESASSOCIADA.value,
            )
            assunto = "ArClear: desassociação confirmada pela prefeitura"
            corpo = (
                f"A Prefeitura de {prefeitura_nome} validou a desassociação da "
                f"empresa {empresa.razao_social}. O acesso ao sistema foi encerrado."
            )
        else:
            empresa.desassociacao_solicitada = False
            empresa.motivo_desassociacao = None
            empresa.data_solicitacao_desassociacao = None
            detalhe = dados.motivo_resposta or "recusada pela prefeitura"
            self._registrar_historico(
                db=db,
                empresa_id=empresa.id,
                autor_id=gestor_id,
                autor_nome=gestor_nome,
                campo="desassociacao_solicitada",
                anterior="true",
                novo=f"recusada: {detalhe}",
            )
            assunto = "ArClear: solicitação de desassociação não aprovada"
            corpo = (
                f"A Prefeitura de {prefeitura_nome} analisou o pedido de "
                f"desassociação da empresa {empresa.razao_social} e manteve o vínculo "
                f"ativo. Observação: {detalhe}"
            )

        db.commit()
        db.refresh(empresa)

        email_service.enviar(destinatario=empresa.email, assunto=assunto, corpo=corpo)
        return empresa

    def listar_historico(self, db: Session, empresa_id: str) -> list[HistoricoCadastro]:
        return (
            db.query(HistoricoCadastro)
            .filter(HistoricoCadastro.empresa_id == empresa_id)
            .order_by(HistoricoCadastro.created_at.desc())
            .all()
        )

    def _validar_troca_de_cnpj(
        self, db: Session, empresa: Empresa, novo_cnpj: str
    ) -> None:
        if empresa.empresa_status != StatusVinculo.AGUARDANDO_VALIDACAO:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O CNPJ não pode ser alterado após a validação do cadastro.",
            )
        if db.query(Empresa).filter(Empresa.cnpj == novo_cnpj).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CNPJ já cadastrado.",
            )


empresa_service = EmpresaService()
