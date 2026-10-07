from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Query, Session

from src.core.database import get_db
from src.core.security import get_current_user, require_empresa, require_superuser
from src.models.models import Empresa, Registro
from src.schemas.enums import StatusValidacao
from src.schemas.schemas import RegistroCreate, RegistroResponse
from src.services.services import registro_service

router = APIRouter(prefix="/registros", tags=["Registros"])


class ValidacaoRequest(BaseModel):
    volume_validado: float


def registros_visiveis(db: Session, usuario: dict[str, Any]) -> Query:
    if usuario["user_type"] == "PREFEITURA":
        return (
            db.query(Registro)
            .join(Registro.empresa)
            .filter(Empresa.prefeitura_id == usuario["prefeitura_id"])
        )

    require_empresa(usuario)
    return db.query(Registro).filter(Registro.empresa_id == usuario["empresa_id"])


@router.post("/", response_model=RegistroResponse, status_code=status.HTTP_201_CREATED)
def criar_registro(
    registro_in: RegistroCreate,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_empresa)],
):
    """
    Recebe um novo registro da empresa autenticada
    (geralmente enviado pelo app mobile via sincronização).
    """
    novo_registro = Registro(
        empresa_id=usuario["empresa_id"],
        material_id=registro_in.material_id,
        periodo=registro_in.periodo,
        volume_total_original=registro_in.volume_total,
        percentual_reciclado=registro_in.percentual_reciclado,
    )

    db.add(novo_registro)
    db.commit()
    db.refresh(novo_registro)

    return novo_registro


@router.get("/", response_model=list[RegistroResponse])
def listar_registros(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(get_current_user)],
    empresa_id: str | None = None,
    status_validacao: StatusValidacao | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Lista os registros, do mais recente para o mais antigo.
    A empresa vê apenas os próprios registros; a prefeitura vê os das empresas
    do seu município. Pode ser filtrado por empresa_id e status_validacao.
    """
    query = registros_visiveis(db, usuario)
    if empresa_id:
        query = query.filter(Registro.empresa_id == empresa_id)
    if status_validacao:
        query = query.filter(Registro.status_validacao == status_validacao)

    registros = (
        query.order_by(Registro.created_at.desc()).offset(skip).limit(limit).all()
    )
    return registros


@router.patch("/{registro_id}/validar", response_model=RegistroResponse)
def validar_registro(
    registro_id: str,
    dados_validacao: ValidacaoRequest,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[dict[str, Any], Depends(require_superuser)],
):
    """
    Endpoint utilizado pelo Gestor de Resíduos da Prefeitura para validar a pesagem.
    Só valida registros de empresas do próprio município.
    Executa o cálculo do carbono evitado e a estimativa financeira via RegistroService.
    """
    registro_atualizado = registro_service.validar_e_calcular(
        db=db,
        registro_id=registro_id,
        validador_id=usuario["id"],
        volume_validado=dados_validacao.volume_validado,
        prefeitura_id=usuario["prefeitura_id"],
    )

    return registro_atualizado
