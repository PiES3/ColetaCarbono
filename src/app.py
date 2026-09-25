import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.database import engine
from src.routers import empresas, materiais, registro


@asynccontextmanager
async def lifespan(app: FastAPI):
    for script in ("create_db.sql", "seed_dev.sql"):
        script_path = os.path.join(os.path.dirname(__file__), script)

        if os.path.exists(script_path):
            with open(script_path, encoding="utf-8") as file:
                sql_script = file.read()

            with engine.begin() as conn:
                conn.connection.executescript(sql_script)

    yield


app = FastAPI(
    title="ColetaCarbono",
    version="0.1.0",
    redirect_slashes=False,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(registro.router)
app.include_router(empresas.router)
app.include_router(materiais.router)
