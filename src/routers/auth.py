from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import get_current_user
from src.schemas.schemas import (
    ConfirmacaoEmailRequest,
    CurrentUserResponse,
    EmpresaCreate,
    EmpresaResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenResponse,
)
from src.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post(
    "/register",
    response_model=EmpresaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar nova empresa vinculada a uma prefeitura",
)
def registrar_empresa(
    empresa_in: EmpresaCreate, db: Annotated[Session, Depends(get_db)]
):
    """
    Permite que uma empresa realize o autocadastro utilizando CNPJ, e-mail, senha
    e selecionando a prefeitura à qual deseja se vincular.
    A empresa é registrada com o status 'AGUARDANDO_VALIDACAO'.
    """
    return auth_service.register_company(db=db, dados=empresa_in)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login unificado para Prefeitura (Superusuário) e Empresa",
)
def login(login_data: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    """
    Autentica entidades (Prefeitura ou Empresa) através de e-mail e senha.
    Retorna o token JWT e as informações e permissões da entidade.
    """
    return auth_service.authenticate_user(
        db=db, email=login_data.email, senha=login_data.senha
    )


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Obter informações da entidade autenticada",
)
def obter_usuario_atual(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Retorna os dados da entidade autenticada a partir do token Bearer.
    """
    return CurrentUserResponse(
        id=current_user["id"],
        email=current_user["email"],
        nome=current_user["nome"],
        user_type=current_user["user_type"],
        is_superuser=current_user["is_superuser"],
        prefeitura_id=current_user.get("prefeitura_id"),
        prefeitura_nome=current_user.get("prefeitura_nome"),
        status_vinculo=current_user.get("status_vinculo"),
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Solicitar redefinição de senha",
)
def solicitar_redefinicao_senha(
    dados: ForgotPasswordRequest, db: Annotated[Session, Depends(get_db)]
):
    """
    Inicia o fluxo de recuperação de senha gerando um token e enviando por e-mail.
    Por segurança, retorna a mesma mensagem de confirmação para e-mails cadastrados
    e não cadastrados, prevenindo a enumeração de contas.
    """
    return auth_service.request_password_reset(db=db, email=dados.email)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Redefinir senha com token",
)
def redefinir_senha(
    dados: ResetPasswordRequest, db: Annotated[Session, Depends(get_db)]
):
    """
    Redefine a senha do usuário utilizando o token de recuperação.
    - Exige que a nova senha atenda à política de complexidade mínima do projeto.
    - O token é de uso único e expira dentro do prazo definido.
    - Todas as sessões anteriores ativas são invalidadas após o reset.
    """
    return auth_service.reset_password(
        db=db, token=dados.token, nova_senha=dados.nova_senha
    )


@router.get(
    "/confirm-email",
    response_model=MessageResponse,
    summary="Confirmar o e-mail da empresa",
)
def confirmar_email(token: str, db: Annotated[Session, Depends(get_db)]):
    """
    Confirma o e-mail pelo link enviado no cadastro. Depois disso, o cadastro
    entra na fila de aprovação do gestor da prefeitura.
    """
    return auth_service.confirm_email(db=db, token=token)


@router.post(
    "/resend-confirmation",
    response_model=MessageResponse,
    summary="Reenviar o link de confirmação de e-mail",
)
def reenviar_confirmacao(
    dados: ConfirmacaoEmailRequest, db: Annotated[Session, Depends(get_db)]
):
    """
    Gera um novo link de confirmação. A resposta é sempre a mesma,
    para não revelar quais e-mails têm cadastro.
    """
    return auth_service.resend_confirmation(db=db, email=dados.email)
