"""
Configuração central da aplicação.

O arquivo `.env` é carregado aqui, antes de qualquer leitura de variável de
ambiente, para que todos os módulos enxerguem os mesmos valores
independentemente da ordem de importação.
"""

import os

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def _env_bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None or not valor.strip():
        return padrao
    return valor.strip().lower() in ("1", "true", "yes", "sim", "on")


def _env_int(nome: str, padrao: int) -> int:
    valor = os.getenv(nome)
    if valor is None or not valor.strip():
        return padrao
    return int(valor)


def _env_list(nome: str, padrao: list[str]) -> list[str]:
    valor = os.getenv(nome)
    if valor is None or not valor.strip():
        return padrao
    return [item.strip() for item in valor.split(",") if item.strip()]


_SECRET_KEY_DEV = "coleta-carbono-dev-secret-key-troque-em-producao-32+"

DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./carbono.db"

SECRET_KEY = os.getenv("SECRET_KEY") or _SECRET_KEY_DEV
if SECRET_KEY == _SECRET_KEY_DEV:
    logger.warning(
        "SECRET_KEY não definida: usando chave de desenvolvimento. "
        "Defina SECRET_KEY no .env antes de publicar a aplicação."
    )

ACCESS_TOKEN_EXPIRE_MINUTES = _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 10080)
RESET_TOKEN_EXPIRE_MINUTES = _env_int("RESET_TOKEN_EXPIRE_MINUTES", 15)
CONFIRM_TOKEN_EXPIRE_MINUTES = _env_int("CONFIRM_TOKEN_EXPIRE_MINUTES", 1440)

PUBLIC_API_URL = (os.getenv("PUBLIC_API_URL") or "http://localhost:8000").rstrip("/")

CORS_ORIGINS = _env_list("CORS_ORIGINS", ["*"])
SEED_DEV_DATA = _env_bool("SEED_DEV_DATA", True)

SERVER_IP_ADDR = os.getenv("SERVER_IP_ADDR") or "127.0.0.1"
SERVER_PORT = _env_int("SERVER_PORT", 8000)
SERVER_RELOAD = _env_bool("SERVER_RELOAD", True)
