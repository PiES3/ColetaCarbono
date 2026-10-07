import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.orm import Session

from src.core.security import (
    RESET_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash_signature,
    hash_password,
    validate_password_complexity,
    verify_password,
)
from src.models.models import (
    Empresa,
    Prefeitura,
    TokenRedefinicaoSenha,
    UsuarioAdmin,
    UsuarioEmpresa,
)
from src.schemas.enums import StatusVinculo
from src.schemas.schemas import EmpresaCreate, TokenResponse


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
                    detail="CNPJ já registado.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já registado.",
            )

        # 3. Verifica se o email já é utilizado por um admin de prefeitura
        admin_existente = (
            db.query(UsuarioAdmin).filter(UsuarioAdmin.email == dados.email).first()
        )
        if admin_existente:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já registado para um administrador da prefeitura.",
            )

        # 4. Garante razão social preenchida
        razao_social = (
            dados.razao_social or dados.nome_fantasia or f"Empresa {dados.cnpj}"
        )

        nova_empresa = Empresa(
            prefeitura_id=dados.prefeitura_id,
            cnpj=dados.cnpj,
            razao_social=razao_social,
            nome_fantasia=dados.nome_fantasia,
            email=dados.email,
            telefone=dados.telefone,
            endereco=dados.endereco,
            pwd_hash=hash_password(dados.senha),
            empresa_status=StatusVinculo.AGUARDANDO_VALIDACAO,
        )

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
                status_vinculo=None,
            )

        # 2. Verifica se é uma Empresa
        empresa = db.query(Empresa).filter(Empresa.email == email).first()
        if empresa and verify_password(senha, empresa.pwd_hash):
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
                status_vinculo=empresa.empresa_status,
            )

        # 3. Verifica se é um Usuário de Empresa
        user_empresa = (
            db.query(UsuarioEmpresa).filter(UsuarioEmpresa.email == email).first()
        )
        if user_empresa and verify_password(senha, user_empresa.senha_hash):
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
                prefeitura_id=None,
                status_vinculo=None,
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

            logger.info(
                f"[EmailService] Enviando e-mail de redefinição para: {email} "
                f"| Token: {token}"
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


auth_service = AuthService()
