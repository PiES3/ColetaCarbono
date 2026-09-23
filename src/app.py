from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from src.core.base import Base # Importa a base correta
from src.core.database import engine
from src.routers import registro

# IMPORTANTE: Você precisa importar os models aqui para que o 
# SQLAlchemy leia as classes antes de executar o create_all.
# Ajuste o caminho do import conforme a sua estrutura.
import src.models.models 

@asynccontextmanager
async def lifespan(app: FastAPI):
    script_path = os.path.join(os.path.dirname(__file__), "create_db.sql")
    
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as file:
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

app.include_router(registro.router)