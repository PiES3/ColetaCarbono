from typing import Annotated

from fastapi import Query

from src.schemas.validacao import PADRAO_PERIODO

PeriodoConsulta = Annotated[str | None, Query(pattern=PADRAO_PERIODO.pattern)]
