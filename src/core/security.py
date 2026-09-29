import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.models import Empresa, UsuarioAdmin

SECRET_KEY = os.getenv(
    "SECRET_KEY", "coleta-carbono-secret-key-super-secure-at-least-32-chars-long"
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

http_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Gera o hash da senha usando bcrypt."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha em texto claro bate com o hash."""
    if not hashed_password:
        return False
    # Compatibilidade retroativa para dados mockados em seeds dev
    if hashed_password.startswith("hashed_"):
        return f"hashed_{plain_password}" == hashed_password
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """Cria um token JWT com data de expiração e claims do usuário."""
    to_encode = data.copy()
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica e valida o token JWT."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_current_user(
    auth: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Dependência FastAPI que extrai o usuário atual a partir do Bearer Token.
    Funciona tanto para usuários da Prefeitura quanto para Empresas.
    """
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(auth.credentials)
    user_id: str | None = payload.get("sub")
    user_type: str | None = payload.get("user_type")

    if not user_id or not user_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token com formato inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user_type == "PREFEITURA":
        admin = db.query(UsuarioAdmin).filter(UsuarioAdmin.id == user_id).first()
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Administrador da prefeitura não encontrado.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {
            "id": admin.id,
            "email": admin.email,
            "nome": admin.nome,
            "user_type": "PREFEITURA",
            "is_superuser": True,
            "prefeitura_id": admin.id_prefeitura,
            "status_vinculo": None,
            "instance": admin,
        }

    if user_type == "EMPRESA":
        empresa = db.query(Empresa).filter(Empresa.id == user_id).first()
        if not empresa:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empresa não encontrada.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {
            "id": empresa.id,
            "email": empresa.email,
            "nome": empresa.nome_fantasia or empresa.razao_social,
            "user_type": "EMPRESA",
            "is_superuser": False,
            "prefeitura_id": empresa.prefeitura_id,
            "status_vinculo": empresa.empresa_status,
            "instance": empresa,
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Tipo de usuário desconhecido no token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


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


def require_empresa(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Exige que o usuário autenticado seja uma Empresa."""
    if current_user.get("user_type") != "EMPRESA":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a Empresas.",
        )
    return current_user
