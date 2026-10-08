import os
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.core.security import (
    CONFIRM_TOKEN_EXPIRE_MINUTES,
    RESET_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash_signature,
    hash_password,
    validate_password_complexity,
    verify_password,
)
from src.models.models import (
    Empresa,
    HistoricoCadastro,
    Prefeitura,
    TokenRedefinicaoSenha,
    UsuarioAdmin,
    UsuarioEmpresa,
)
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import EmpresaCreate, TokenResponse
from src.services.email_service import email_service


class AuthService:
    def register_company(self, db: Session, dados: EmpresaCreate) -> Empresa:
        """
        Cadastra uma nova empresa vinculada a uma prefeitura existente.
        A empresa nasce com o status AGUARDANDO_VALIDACAO.
        """
        # 1. Verifica se a prefeitura selecionada existe
        prefeitura = (
            db.query(Prefeitura).filter(Prefeitura.id == dados.prefeitura_id).first()
        )
        if not prefeitura:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prefeitura não encontrada.",
            )

        # 2. Verifica unicidade de CNPJ e Email entre empresas
        empresa_existente = (
            db.query(Empresa)
            .filter((Empresa.cnpj == dados.cnpj) | (Empresa.email == dados.email))
            .first()
        )
        if empresa_existente:
            if empresa_existente.cnpj == dados.cnpj:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="CNPJ já cadastrado.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já cadastrado.",
            )

        # 3. Verifica se o email já é utilizado por um admin de prefeitura
        admin_existente = (
            db.query(UsuarioAdmin).filter(UsuarioAdmin.email == dados.email).first()
        )
        if admin_existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já cadastrado para um administrador da prefeitura.",
            )

        usuario_existente = (
            db.query(UsuarioEmpresa).filter(UsuarioEmpresa.email == dados.email).first()
        )
        if usuario_existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já cadastrado.",
            )

        nova_empresa = Empresa(
            prefeitura_id=dados.prefeitura_id,
            cnpj=dados.cnpj,
            razao_social=dados.razao_social,
            nome_fantasia=dados.nome_fantasia,
            email=dados.email,
            telefone=dados.telefone,
            endereco=dados.endereco,
            pwd_hash=hash_password(dados.senha),
            empresa_status=StatusVinculo.AGUARDANDO_VALIDACAO,
        )
        self.gerar_token_confirmacao(nova_empresa)

        db.add(nova_empresa)
        db.commit()
        db.refresh(nova_empresa)
        return nova_empresa

    def authenticate_user(self, db: Session, email: str, senha: str) -> TokenResponse:
        """
        Autentica a entidade pelo e-mail e senha.
        Diferencia permissões:
        - Prefeitura (UsuarioAdmin): atua como superusuário (user_type = 'PREFEITURA').
        - Empresa: permissões padrão de empresa (user_type = 'EMPRESA').
        """
        # 1. Verifica se é um usuário da Prefeitura (Superusuário)
        admin = db.query(UsuarioAdmin).filter(UsuarioAdmin.email == email).first()
        if admin and verify_password(senha, admin.senha_hash):
            token_payload = {
                "sub": admin.id,
                "email": admin.email,
                "user_type": "PREFEITURA",
                "is_superuser": True,
                "id_prefeitura": admin.id_prefeitura,
                "pwd_sig": get_password_hash_signature(admin.senha_hash),
            }
            access_token = create_access_token(token_payload)
            return TokenResponse(
                access_token=access_token,
                token_type="bearer",
                user_type="PREFEITURA",
                user_id=admin.id,
                email=admin.email,
                nome=admin.nome,
                prefeitura_id=admin.id_prefeitura,
                prefeitura_nome=admin.prefeitura.nome,
                status_vinculo=None,
            )

        # 2. Verifica se é uma Empresa
        empresa = db.query(Empresa).filter(Empresa.email == email).first()
        if empresa and verify_password(senha, empresa.pwd_hash):
            self._barrar_empresa_nao_liberada(empresa)
            token_payload = {
                "sub": empresa.id,
                "email": empresa.email,
                "user_type": "EMPRESA",
                "is_superuser": False,
                "prefeitura_id": empresa.prefeitura_id,
                "status_vinculo": (
                    empresa.empresa_status.value
                    if hasattr(empresa.empresa_status, "value")
                    else str(empresa.empresa_status)
                ),
                "pwd_sig": get_password_hash_signature(empresa.pwd_hash),
            }
            access_token = create_access_token(token_payload)
            nome_empresa = empresa.nome_fantasia or empresa.razao_social
            return TokenResponse(
                access_token=access_token,
                token_type="bearer",
                user_type="EMPRESA",
                user_id=empresa.id,
                email=empresa.email,
                nome=nome_empresa,
                prefeitura_id=empresa.prefeitura_id,
                prefeitura_nome=empresa.prefeitura.nome,
                status_vinculo=empresa.empresa_status,
            )

        # 3. Verifica se é um Usuário de Empresa
        user_empresa = (
            db.query(UsuarioEmpresa).filter(UsuarioEmpresa.email == email).first()
        )
        if user_empresa and verify_password(senha, user_empresa.senha_hash):
            self._barrar_empresa_nao_liberada(user_empresa.empresa)
            token_payload = {
                "sub": user_empresa.id,
                "email": user_empresa.email,
                "user_type": "USUARIO_EMPRESA",
                "is_superuser": False,
                "empresa_id": user_empresa.id_empresa,
                "pwd_sig": get_password_hash_signature(user_empresa.senha_hash),
            }
            access_token = create_access_token(token_payload)
            return TokenResponse(
                access_token=access_token,
                token_type="bearer",
                user_type="USUARIO_EMPRESA",
                user_id=user_empresa.id,
                email=user_empresa.email,
                nome=user_empresa.nome,
                prefeitura_id=user_empresa.empresa.prefeitura_id,
                prefeitura_nome=user_empresa.empresa.prefeitura.nome,
                status_vinculo=user_empresa.empresa.empresa_status,
            )

        # 4. Credenciais não encontradas ou inválidas
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def request_password_reset(self, db: Session, email: str) -> dict[str, str]:
        """
        Gera um token de redefinição de senha caso o e-mail esteja cadastrado.
        Por motivos de segurança, a mensagem retornada é idêntica tanto para
        e-mails cadastrados quanto para não cadastrados (evita enumeração).
        """
        admin = db.query(UsuarioAdmin).filter(UsuarioAdmin.email == email).first()
        empresa = db.query(Empresa).filter(Empresa.email == email).first()
        user_empresa = (
            db.query(UsuarioEmpresa).filter(UsuarioEmpresa.email == email).first()
        )

        if admin or empresa or user_empresa:
            # Invalida tokens anteriores não utilizados para este e-mail
            db.query(TokenRedefinicaoSenha).filter(
                TokenRedefinicaoSenha.email == email,
                TokenRedefinicaoSenha.utilizado.is_(False),
            ).update({"utilizado": True})

            token = secrets.token_urlsafe(32)
            agora = datetime.now(UTC)
            expiracao = agora + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

            token_record = TokenRedefinicaoSenha(
                email=email,
                token=token,
                expiracao=expiracao,
                utilizado=False,
            )
            db.add(token_record)
            db.commit()

            email_service.enviar(
                destinatario=email,
                assunto="ArClear: código para redefinir sua senha",
                corpo=(
                    "Recebemos um pedido para redefinir a senha da sua conta "
                    "no ArClear.\n\n"
                    f"Código: {token}\n\n"
                    "Copie o código e cole no aplicativo, na tela Recuperar senha. "
                    f"Ele vale por {RESET_TOKEN_EXPIRE_MINUTES} minutos e só pode "
                    "ser usado uma vez.\n\n"
                    "Se você não pediu a troca, ignore este e-mail. "
                    "Sua senha continua a mesma."
                ),
            )

        return {
            "message": (
                "Se o e-mail estiver cadastrado, as instruções e o token de "
                "redefinição foram enviados."
            )
        }

    def reset_password(
        self, db: Session, token: str, nova_senha: str
    ) -> dict[str, str]:
        """
        Redefine a senha utilizando o token de recuperação.
        Critérios atendidos:
        - Validação de complexidade da nova senha.
        - Validação de expiração e uso único do token.
        - Invalidação de todas as sessões anteriores ativas.
        """
        # 1. Validação de complexidade mínima da nova senha
        validate_password_complexity(nova_senha)

        # 2. Busca do token no banco
        token_record = (
            db.query(TokenRedefinicaoSenha)
            .filter(TokenRedefinicaoSenha.token == token)
            .first()
        )
        if not token_record or token_record.utilizado:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token inválido ou já utilizado.",
            )

        # 3. Verificação de expiração
        agora = datetime.now(UTC)
        expiracao = token_record.expiracao
        if expiracao.tzinfo is None:
            expiracao = expiracao.replace(tzinfo=UTC)

        if agora > expiracao:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token expirado. Solicite uma nova recuperação de senha.",
            )

        # 4. Localiza o usuário associado
        admin = (
            db.query(UsuarioAdmin)
            .filter(UsuarioAdmin.email == token_record.email)
            .first()
        )
        empresa = db.query(Empresa).filter(Empresa.email == token_record.email).first()
        user_empresa = (
            db.query(UsuarioEmpresa)
            .filter(UsuarioEmpresa.email == token_record.email)
            .first()
        )

        if not (admin or empresa or user_empresa):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuário associado a este token não foi encontrado.",
            )

        # 5. Atualiza a senha gerando novo hash bcrypt
        novo_hash = hash_password(nova_senha)
        if admin:
            admin.senha_hash = novo_hash
        if empresa:
            empresa.pwd_hash = novo_hash
        if user_empresa:
            user_empresa.senha_hash = novo_hash

        # 6. Invalida o token após o primeiro uso
        token_record.utilizado = True
        db.query(TokenRedefinicaoSenha).filter(
            TokenRedefinicaoSenha.email == token_record.email,
            TokenRedefinicaoSenha.utilizado.is_(False),
        ).update({"utilizado": True})

        db.commit()

        logger.info(
            f"[AuthService] Senha redefinida para {token_record.email}. "
            "Sessões anteriores invalidadas."
        )

        return {
            "message": (
                "Senha redefinida com sucesso. Todas as sessões ativas foram "
                "encerradas. Faça login com a nova senha."
            )
        }

    def confirm_email(self, db: Session, token: str) -> dict[str, str]:
        """
        Confirma o e-mail da empresa pelo token enviado no cadastro.
        Depois disso, o cadastro entra na fila de aprovação do gestor.
        """
        empresa = (
            db.query(Empresa).filter(Empresa.token_confirmacao_email == token).first()
        )
        if not empresa:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Link de confirmação inválido ou já utilizado.",
            )

        expiracao = empresa.token_expiracao
        if expiracao and expiracao.tzinfo is None:
            expiracao = expiracao.replace(tzinfo=UTC)
        if not expiracao or datetime.now(UTC) > expiracao:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Link de confirmação expirado. Peça um novo no aplicativo.",
            )

        if empresa.email_pendente:
            return self._aplicar_troca_de_email(db, empresa)

        empresa.email_confirmado = True
        empresa.token_confirmacao_email = None
        empresa.token_expiracao = None
        db.commit()

        return {
            "message": (
                "E-mail confirmado. Agora a prefeitura vai analisar seu cadastro."
            )
        }

    def resend_confirmation(self, db: Session, email: str) -> dict[str, str]:
        """
        Gera um novo token de confirmação de e-mail, seja do cadastro ou de uma
        troca de e-mail pendente.
        A mensagem é sempre a mesma, para não revelar quais e-mails têm cadastro.
        """
        empresa = (
            db.query(Empresa)
            .filter(or_(Empresa.email == email, Empresa.email_pendente == email))
            .first()
        )
        if empresa and empresa.email_pendente == email:
            self.gerar_token_confirmacao(empresa, destino=email)
            db.commit()
        elif (
            empresa
            and not empresa.email_confirmado
            and empresa.empresa_status == StatusVinculo.AGUARDANDO_VALIDACAO
        ):
            self.gerar_token_confirmacao(empresa)
            db.commit()

        return {
            "message": (
                "Se houver um cadastro aguardando confirmação, enviamos um novo link."
            )
        }

    def email_em_uso(
        self, db: Session, email: str, ignorar_empresa_id: str | None = None
    ) -> bool:
        empresas = db.query(Empresa).filter(
            or_(Empresa.email == email, Empresa.email_pendente == email)
        )
        if ignorar_empresa_id:
            empresas = empresas.filter(Empresa.id != ignorar_empresa_id)

        admin = db.query(UsuarioAdmin).filter(UsuarioAdmin.email == email)
        usuario = db.query(UsuarioEmpresa).filter(UsuarioEmpresa.email == email)
        return any(q.first() is not None for q in (empresas, admin, usuario))

    def gerar_token_confirmacao(
        self, empresa: Empresa, destino: str | None = None
    ) -> None:
        empresa.token_confirmacao_email = secrets.token_urlsafe(32)
        empresa.token_expiracao = datetime.now(UTC) + timedelta(
            minutes=CONFIRM_TOKEN_EXPIRE_MINUTES
        )

        base = os.getenv("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
        link = f"{base}/auth/confirm-email?token={empresa.token_confirmacao_email}"
        if CONFIRM_TOKEN_EXPIRE_MINUTES % 60 == 0:
            prazo = f"{CONFIRM_TOKEN_EXPIRE_MINUTES // 60} horas"
        else:
            prazo = f"{CONFIRM_TOKEN_EXPIRE_MINUTES} minutos"

        if destino:
            assunto = "ArClear: confirme o novo e-mail da sua empresa"
            pedido = (
                "Recebemos um pedido para usar este endereço como o novo e-mail "
                "da sua empresa no ArClear. Para confirmar, abra o link abaixo:"
            )
            depois = "Até a confirmação, o login continua com o e-mail anterior."
        else:
            assunto = "ArClear: confirme seu e-mail"
            pedido = (
                "Para confirmar o e-mail do cadastro da sua empresa no ArClear, "
                "abra o link abaixo:"
            )
            depois = "Depois da confirmação, a prefeitura analisa o seu cadastro."

        email_service.enviar(
            destinatario=destino or empresa.email,
            assunto=assunto,
            corpo=f"{pedido}\n\n{link}\n\nO link vale por {prazo}. {depois}",
        )

    def _aplicar_troca_de_email(self, db: Session, empresa: Empresa) -> dict[str, str]:
        novo_email = empresa.email_pendente
        if self.email_em_uso(db, novo_email, ignorar_empresa_id=empresa.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Este e-mail passou a ser usado por outra conta. "
                    "Solicite a troca novamente."
                ),
            )

        db.add(
            HistoricoCadastro(
                empresa_id=empresa.id,
                autor_id=empresa.id,
                autor_nome=empresa.nome_fantasia or empresa.razao_social,
                campo="email",
                valor_anterior=empresa.email,
                valor_novo=novo_email,
            )
        )
        empresa.email = novo_email
        empresa.email_pendente = None
        empresa.email_confirmado = True
        empresa.token_confirmacao_email = None
        empresa.token_expiracao = None
        db.commit()

        return {"message": "E-mail atualizado. Use o novo e-mail para entrar."}

    def _barrar_empresa_nao_liberada(self, empresa: Empresa) -> None:
        if empresa.empresa_status == StatusVinculo.APROVADA:
            return

        prefeitura = f"Prefeitura de {empresa.prefeitura.nome}"

        if empresa.empresa_status == StatusVinculo.AGUARDANDO_VALIDACAO:
            if not empresa.email_confirmado:
                codigo = "EMAIL_NAO_CONFIRMADO"
                mensagem = (
                    f"Enviamos um link para {empresa.email}. Depois de confirmar, "
                    f"a {prefeitura} analisa seu cadastro."
                )
            else:
                codigo = "CADASTRO_PENDENTE"
                mensagem = (
                    f"Seu e-mail já foi confirmado. Falta a {prefeitura} aprovar "
                    "o vínculo da sua empresa. Avisaremos por e-mail."
                )
        elif empresa.empresa_status == StatusVinculo.RECUSADA:
            codigo = "CADASTRO_RECUSADO"
            motivo = empresa.motivo_recusa or "não informado"
            mensagem = f"A {prefeitura} recusou o vínculo. Motivo: {motivo}"
        else:
            codigo = "CADASTRO_DESASSOCIADO"
            mensagem = f"Sua empresa não está mais vinculada à {prefeitura}."

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"codigo": codigo, "mensagem": mensagem},
        )


auth_service = AuthService()
