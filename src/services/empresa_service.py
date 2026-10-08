from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.models.models import Empresa, HistoricoCadastro
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import EmpresaUpdate
from src.services.auth_service import auth_service

CAMPOS_EDITAVEIS = ("razao_social", "nome_fantasia", "telefone", "endereco")


class EmpresaService:
    def atualizar_dados(
        self,
        db: Session,
        empresa: Empresa,
        dados: EmpresaUpdate,
        autor_id: str,
        autor_nome: str,
    ) -> Empresa:
        """
        Atualiza os dados cadastrais da empresa (HU006).
        Cada campo alterado fica registrado no histórico com autor e data/hora.
        A troca de e-mail só vale depois da confirmação pelo link enviado
        ao novo endereço, e o CNPJ não muda depois da validação do cadastro.
        """
        alteracoes = dados.model_dump(exclude_unset=True)

        def registrar(campo: str, anterior: str | None, novo: str | None) -> None:
            db.add(
                HistoricoCadastro(
                    empresa_id=empresa.id,
                    autor_id=autor_id,
                    autor_nome=autor_nome,
                    campo=campo,
                    valor_anterior=anterior,
                    valor_novo=novo,
                )
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
