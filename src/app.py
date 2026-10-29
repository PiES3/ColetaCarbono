from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import Boolean, Float, Integer, inspect, text

from src.core.base import Base
from src.core.config import CORS_ORIGINS, SEED_DEV_DATA
from src.core.database import IS_SQLITE, engine
from src.models import models  # noqa: F401  (registra as tabelas no metadata)
from src.routers import (
    auth,
    dashboard,
    empresas,
    health,
    materiais,
    prefeituras,
    registro,
    relatorios,
)

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


def _ddl_coluna_aditiva_sqlite(coluna) -> str | None:
    """Gera cláusula ADD COLUMN para colunas anuláveis ou com default escalar."""
    if isinstance(coluna.type, Boolean):
        padrao = " DEFAULT 0"
    elif isinstance(coluna.type, Integer):
        padrao = " DEFAULT 0" if not coluna.nullable else ""
    elif isinstance(coluna.type, Float):
        padrao = " DEFAULT 0.0" if not coluna.nullable else ""
    else:
        if not coluna.nullable and coluna.default is None:
            return None
        padrao = ""

    tipo_sql = (
        "INTEGER"
        if isinstance(coluna.type, (Boolean, Integer))
        else "REAL"
        if isinstance(coluna.type, Float)
        else "TEXT"
    )
    not_null = " NOT NULL" if (not coluna.nullable and padrao) else ""
    return f"{coluna.name} {tipo_sql}{not_null}{padrao}"


def migrar_colunas_ausentes() -> None:
    """Aplica migração aditiva segura no SQLite para novas colunas do modelo."""
    inspetor = inspect(engine)
    tabelas = set(inspetor.get_table_names())
    with engine.begin() as conn:
        for tabela in Base.metadata.sorted_tables:
            if tabela.name not in tabelas:
                continue
            existentes = {col["name"] for col in inspetor.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name in existentes:
                    continue
                definicao = _ddl_coluna_aditiva_sqlite(coluna)
                if definicao:
                    logger.info(
                        f"Adicionando coluna ausente '{tabela.name}.{coluna.name}'"
                    )
                    conn.execute(
                        text(f"ALTER TABLE {tabela.name} ADD COLUMN {definicao}")
                    )


def verificar_schema() -> None:
    """
    Verifica se todas as tabelas e colunas esperadas pelos modelos existem no
    banco após os scripts e migrações aditivas.
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
    migrar_colunas_ausentes()
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

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(registro.router)
app.include_router(empresas.router)
app.include_router(materiais.router)
app.include_router(prefeituras.router)
app.include_router(dashboard.router)
app.include_router(relatorios.router)
