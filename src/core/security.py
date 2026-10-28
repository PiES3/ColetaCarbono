import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    CONFIRM_TOKEN_EXPIRE_MINUTES,
    RESET_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
)
from src.core.database import get_db
from src.models.models import Empresa, UsuarioAdmin, UsuarioEmpresa
from src.schemas.enums import StatusVinculo

__all__ = [
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "ALGORITHM",
    "CONFIRM_TOKEN_EXPIRE_MINUTES",
    "RESET_TOKEN_EXPIRE_MINUTES",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "get_current_user_optional",
    "get_password_hash_signature",
    "hash_password",
    "require_empresa",
    "require_gestor",
    "require_superuser",
    "validate_password_complexity",
    "verify_password",
]

ALGORITHM = "HS256"
SENHA_TAMANHO_MIN = 8
# O bcrypt considera apenas os primeiros 72 bytes da senha.
SENHA_BYTES_MAX = 72

http_bearer = HTTPBearer(auto_error=False)

REGRAS_SENHA: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Z]"), "deve conter pelo menos uma letra maiúscula."),
    (re.compile(r"[a-z]"), "deve conter pelo menos uma letra minúscula."),
    (re.compile(r"\d"), "deve conter pelo menos um número."),
    (
        re.compile(r"[!@#$%^&*(),.?\":{}|<>\-_+=\[\]\\/`~]"),
        "deve conter pelo menos um caractere especial (!@#$%^&* etc.).",
    ),
)


def _nao_autorizado(detalhe: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detalhe,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_password_hash_signature(hashed_password: str) -> str:
    """Gera uma assinatura curta e segura a partir do hash da senha."""
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()[:16]


def validate_password_complexity(password: str, rotulo: str = "A nova senha") -> None:
    """
    Valida os requisitos mínimos de complexidade da senha, no cadastro e na
    redefinição:
    - No mínimo 8 caracteres (e no máximo 72 bytes, limite do bcrypt)
    - Pelo menos uma letra maiúscula
    - Pelo menos uma letra minúscula
    - Pelo menos um dígito numérico
    - Pelo menos um caractere especial (!@#$%^&* etc.)
    """
    if len(password) < SENHA_TAMANHO_MIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{rotulo} deve ter no mínimo {SENHA_TAMANHO_MIN} caracteres.",
        )
    if len(password.encode("utf-8")) > SENHA_BYTES_MAX:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{rotulo} deve ter no máximo {SENHA_BYTES_MAX} caracteres.",
        )
    for padrao, mensagem in REGRAS_SENHA:
        if not padrao.search(password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{rotulo} {mensagem}",
            )


def hash_password(password: str) -> str:
    """Gera o hash da senha usando bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verifica se a senha em texto claro bate com o hash bcrypt."""
    if not hashed_password:
        return False
    senha = plain_password.encode("utf-8")
    if len(senha) > SENHA_BYTES_MAX:
        # bcrypt >= 5 rejeita senhas maiores que 72 bytes com ValueError.
        return False
    try:
        return bcrypt.checkpw(senha, hashed_password.encode("utf-8"))
    except ValueError:
        # Hash malformado no banco: trata como senha incorreta.
        return False


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """Cria um token JWT com data de expiração e claims do usuário."""
    agora = datetime.now(UTC)
    expira = agora + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return jwt.encode(
        {**data, "exp": expira, "iat": agora}, SECRET_KEY, algorithm=ALGORITHM
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica e valida o token JWT."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise _nao_autorizado("Token inválido ou expirado.") from None


def _checar_assinatura_senha(token_sig: str | None, senha_hash: str) -> None:
    """Invalida tokens emitidos antes da última troca de senha."""
    if not token_sig or token_sig != get_password_hash_signature(senha_hash):
        raise _nao_autorizado(
            "Sessão invalidada após alteração de senha. Faça login novamente."
        )


def _usuario_prefeitura(db: Session, user_id: str, token_sig: str | None) -> dict:
    admin = db.get(UsuarioAdmin, user_id)
    if not admin:
        raise _nao_autorizado("Administrador da prefeitura não encontrado.")
    _checar_assinatura_senha(token_sig, admin.senha_hash)
    return {
        "id": admin.id,
        "email": admin.email,
        "nome": admin.nome,
        "user_type": "PREFEITURA",
        "is_superuser": True,
        "prefeitura_id": admin.id_prefeitura,
        "prefeitura_nome": admin.prefeitura.nome,
        "status_vinculo": None,
        "instance": admin,
    }


def _usuario_empresa(db: Session, user_id: str, token_sig: str | None) -> dict:
    empresa = db.get(Empresa, user_id)
    if not empresa:
        raise _nao_autorizado("Empresa não encontrada.")
    _checar_assinatura_senha(token_sig, empresa.pwd_hash)
    return {
        "id": empresa.id,
        "email": empresa.email,
        "nome": empresa.nome_fantasia or empresa.razao_social,
        "user_type": "EMPRESA",
        "is_superuser": False,
        "empresa_id": empresa.id,
        "prefeitura_id": empresa.prefeitura_id,
        "prefeitura_nome": empresa.prefeitura.nome,
        "status_vinculo": empresa.empresa_status,
        "instance": empresa,
    }


def _usuario_da_empresa(db: Session, user_id: str, token_sig: str | None) -> dict:
    usuario = db.get(UsuarioEmpresa, user_id)
    if not usuario:
        raise _nao_autorizado("Usuário da empresa não encontrado.")
    _checar_assinatura_senha(token_sig, usuario.senha_hash)
    empresa = usuario.empresa
    return {
        "id": usuario.id,
        "email": usuario.email,
        "nome": usuario.nome,
        "user_type": "USUARIO_EMPRESA",
        "is_superuser": False,
        "empresa_id": usuario.id_empresa,
        "prefeitura_id": empresa.prefeitura_id,
        "prefeitura_nome": empresa.prefeitura.nome,
        "status_vinculo": empresa.empresa_status,
        "instance": usuario,
    }


_CARREGADORES_DE_USUARIO = {
    "PREFEITURA": _usuario_prefeitura,
    "EMPRESA": _usuario_empresa,
    "USUARIO_EMPRESA": _usuario_da_empresa,
}


def get_current_user(
    auth: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Dependência FastAPI que extrai o usuário atual a partir do Bearer Token.
    Funciona para usuários da Prefeitura, Empresas e usuários de Empresas.
    """
    if not auth or not auth.credentials:
        raise _nao_autorizado("Autenticação necessária.")

    payload = decode_access_token(auth.credentials)
    user_id = payload.get("sub")
    user_type = payload.get("user_type")

    if not isinstance(user_id, str) or not isinstance(user_type, str):
        raise _nao_autorizado("Token com formato inválido.")

    carregar = _CARREGADORES_DE_USUARIO.get(user_type)
    if carregar is None:
        raise _nao_autorizado("Tipo de usuário desconhecido no token.")

    return carregar(db, user_id, payload.get("pwd_sig"))


def require_superuser(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Exige que o usuário autenticado seja a Prefeitura (superuser)."""
    if not current_user.get("is_superuser"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito à Prefeitura (Superusuário).",
        )
    return current_user


def require_gestor(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Exige que o usuário autenticado seja um Gestor da Prefeitura."""
    if (
        not current_user.get("is_superuser")
        or current_user.get("user_type") != "PREFEITURA"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a gestores da prefeitura.",
        )
    return current_user


def get_current_user_optional(
    auth: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any] | None:
    """Extrai o usuário autenticado se presente; retorna None se anônimo."""
    if not auth or not auth.credentials:
        return None
    try:
        return get_current_user(auth=auth, db=db)
    except HTTPException:
        return None


def require_empresa(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Exige que o usuário autenticado seja de uma Empresa com vínculo aprovado."""
    if current_user.get("user_type") not in ("EMPRESA", "USUARIO_EMPRESA"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a Empresas.",
        )
    if current_user.get("status_vinculo") != StatusVinculo.APROVADA:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O vínculo da empresa com a prefeitura não está aprovado.",
        )
    return current_user
