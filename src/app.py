from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import inspect

from src.core.base import Base
from src.core.config import CORS_ORIGINS, SEED_DEV_DATA
from src.core.database import IS_SQLITE, engine
from src.models import models  # noqa: F401  (registra as tabelas no metadata)
from src.routers import auth, empresas, materiais, prefeituras, registro

SRC_DIR = Path(__file__).resolve().parent
SCRIPT_SCHEMA = SRC_DIR / "create_db.sql"
SCRIPT_SEED = SRC_DIR / "seed_dev.sql"


def executar_script_sql(caminho: Path) -> None:
    if not caminho.exists():
        logger.warning(f"Script SQL não encontrado: {caminho}")
        return
    conexao = engine.raw_connection()
    try:
        conexao.driver_connection.executescript(caminho.read_text(encoding="utf-8"))
        conexao.commit()
    finally:
        conexao.close()


def verificar_schema() -> None:
    """
    `CREATE TABLE IF NOT EXISTS` não altera tabelas já existentes. Se o banco
    foi criado por uma versão anterior, avisa com clareza em vez de falhar
    depois com um erro genérico do SQLite.
    """
    inspetor = inspect(engine)
    tabelas = set(inspetor.get_table_names())
    problemas: list[str] = []
    for tabela in Base.metadata.sorted_tables:
        if tabela.name not in tabelas:
            problemas.append(f"tabela '{tabela.name}' ausente")
            continue
        existentes = {coluna["name"] for coluna in inspetor.get_columns(tabela.name)}
        faltando = sorted(set(tabela.columns.keys()) - existentes)
        if faltando:
            problemas.append(f"{tabela.name}: colunas ausentes {faltando}")

    if problemas:
        raise RuntimeError(
            f"O banco de dados ({engine.url}) está com o schema desatualizado: "
            + "; ".join(problemas)
            + ". Apague o arquivo do banco para recriá-lo ou aplique uma migração."
        )


def inicializar_banco() -> None:
    if not IS_SQLITE:
        logger.info("Banco não-SQLite: os scripts de schema/seed não são aplicados.")
        return
    executar_script_sql(SCRIPT_SCHEMA)
    verificar_schema()
    if SEED_DEV_DATA:
        executar_script_sql(SCRIPT_SEED)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    inicializar_banco()
    yield


app = FastAPI(
    title="ColetaCarbono",
    version="0.1.0",
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(registro.router)
app.include_router(empresas.router)
app.include_router(materiais.router)
app.include_router(prefeituras.router)
