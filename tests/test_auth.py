import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.app import app
from src.core.database import get_db
from src.core.security import require_superuser
from src.models.models import Empresa, TokenRedefinicaoSenha

TEST_DATABASE_URL = "sqlite:///./test_carbono.db"
test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db() -> Generator[None, None, None]:
    """Cria e popula o banco de dados de teste via scripts SQL."""
    db_path = Path("test_carbono.db")
    base_dir = Path(__file__).resolve().parent.parent
    
    con = sqlite3.connect(db_path)
    for script in ("create_db.sql", "seed_dev.sql"):
        script_path = base_dir / "src" / script
        if script_path.exists():
            con.executescript(script_path.read_text(encoding="utf-8"))
    con.commit()
    con.close()

    yield

    # Limpeza pós-testes
    db_path.unlink(missing_ok=True)


def override_get_db() -> Generator[Session, None, None]:
    """Sobrescreve a injeção de dependência do FastAPI para usar o banco de teste."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Fixture para simular requisições HTTP."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Fixture de banco de dados para consultas internas nos testes."""
    db_session = TestingSessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


def auth_headers(
    client: TestClient, email: str, senha: str = "demo123"
) -> dict[str, str]:
    """Função auxiliar para gerar headers de autenticação."""
    resposta = client.post("/auth/login", json={"email": email, "senha": senha})
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


# ============================================================================
# Testes de Autocadastro de Empresa
# ============================================================================


def test_register_company_success(client: TestClient):
    payload = {
        "cnpj": "12345678000199",
        "email": "empresa_teste@valida.com",
        "senha": "password123",
        "razao_social": "Empresa Teste LTDA",
        "nome_fantasia": "Teste Corp",
        "telefone": "88999999999",
        "endereco": "Rua Exemplo, 123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    dados = response.json()
    assert dados["cnpj"] == payload["cnpj"]
    assert dados["email"] == payload["email"]
    assert dados["empresa_status"] == "AGUARDANDO VALIDACAO"
    assert "id" in dados


def test_register_company_duplicate_cnpj(client: TestClient):
    payload = {
        "cnpj": "00000000000100",  # Já presente no seed_dev.sql
        "email": "outro_email@empresa.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "CNPJ já registado."


def test_register_company_duplicate_email(client: TestClient):
    payload = {
        "cnpj": "11223344000155",
        "email": "empresa@demo.com",  # Já presente no seed_dev.sql
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "E-mail já registado."


def test_register_company_email_used_by_prefeitura_admin(client: TestClient):
    payload = {
        "cnpj": "55667788000122",
        "email": "gestor@demo.com",  # E-mail de admin da prefeitura
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "E-mail já registado para um administrador da prefeitura."


def test_register_company_nonexistent_prefeitura(client: TestClient):
    payload = {
        "cnpj": "99887766000111",
        "email": "empresa_sem_pref@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-inexistente-123",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Prefeitura não encontrada."


def test_register_company_minimal_fields(client: TestClient):
    payload = {
        "cnpj": "98765432000111",
        "email": "minima@empresa.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    dados = response.json()
    assert dados["razao_social"] == f"Empresa {payload['cnpj']}"


# ============================================================================
# Testes de Autenticação (Login)
# ============================================================================


def test_login_prefeitura_success(client: TestClient):
    response = client.post("/auth/login", json={"email": "gestor@demo.com", "senha": "demo123"})
    assert response.status_code == status.HTTP_200_OK
    dados = response.json()
    assert "access_token" in dados
    assert dados["token_type"] == "bearer"
    assert dados["user_type"] == "PREFEITURA"
    assert dados["email"] == "gestor@demo.com"


def test_login_empresa_success(client: TestClient):
    response = client.post("/auth/login", json={"email": "empresa@demo.com", "senha": "demo123"})
    assert response.status_code == status.HTTP_200_OK
    dados = response.json()
    assert "access_token" in dados
    assert dados["user_type"] == "EMPRESA"
    assert dados["status_vinculo"] == "APROVADA"


def test_login_invalid_password(client: TestClient):
    response = client.post("/auth/login", json={"email": "gestor@demo.com", "senha": "senha_errada"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_login_nonexistent_email(client: TestClient):
    response = client.post("/auth/login", json={"email": "inexistente@demo.com", "senha": "qualquer_senha"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_login_company_confirmation_and_approval_flow(client: TestClient, db: Session):
    prefeitura = auth_headers(client, "gestor@demo.com")
    dados = {
        "cnpj": "22222222000122",
        "email": "fluxo@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    empresa_id = client.post("/auth/register", json=dados).json()["id"]
    login = {"email": dados["email"], "senha": dados["senha"]}

    response = client.post("/auth/login", json=login)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"]["codigo"] == "EMAIL_NAO_CONFIRMADO"

    aprovar = {"novo_status": "APROVADA"}
    url_status = f"/empresas/{empresa_id}/status"
    assert client.patch(url_status, json=aprovar, headers=prefeitura).status_code == status.HTTP_400_BAD_REQUEST

    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    assert empresa is not None
    token = empresa.token_confirmacao_email

    assert client.get("/auth/confirm-email", params={"token": token}).status_code == status.HTTP_200_OK
    assert client.get("/auth/confirm-email", params={"token": token}).status_code == status.HTTP_400_BAD_REQUEST

    assert client.post("/auth/login", json=login).status_code == status.HTTP_403_FORBIDDEN
    assert client.patch(url_status, json=aprovar, headers=prefeitura).status_code == status.HTTP_200_OK
    assert client.post("/auth/login", json=login).status_code == status.HTTP_200_OK


def test_login_refused_company_shows_reason(client: TestClient):
    dados = {
        "cnpj": "44444444000144",
        "email": "recusada@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    empresa_id = client.post("/auth/register", json=dados).json()["id"]
    client.patch(
        f"/empresas/{empresa_id}/status",
        json={"novo_status": "RECUSADA", "motivo_recusa": "CNPJ fora da região"},
        headers=auth_headers(client, "gestor@demo.com"),
    )

    response = client.post("/auth/login", json={"email": dados["email"], "senha": dados["senha"]})
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "CNPJ fora da região" in response.json()["detail"]["mensagem"]


def test_login_wrong_password_on_pending_company_stays_generic(client: TestClient):
    dados = {
        "cnpj": "33333333000133",
        "email": "pendente_senha@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    client.post("/auth/register", json=dados)
    response = client.post("/auth/login", json={"email": dados["email"], "senha": "outra_senha"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_resend_confirmation_same_message(client: TestClient):
    dados = {
        "cnpj": "55555555000155",
        "email": "reenvio@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    client.post("/auth/register", json=dados)

    existente = client.post("/auth/resend-confirmation", json={"email": dados["email"]})
    inexistente = client.post("/auth/resend-confirmation", json={"email": "ninguem@teste.com"})
    
    assert existente.status_code == status.HTTP_200_OK
    assert existente.json() == inexistente.json()


# ============================================================================
# Testes do Endpoint /auth/me e Permissões
# ============================================================================


def test_auth_me_prefeitura(client: TestClient):
    headers = auth_headers(client, "gestor@demo.com")
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["user_type"] == "PREFEITURA"


def test_auth_me_empresa(client: TestClient):
    headers = auth_headers(client, "empresa@demo.com")
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["user_type"] == "EMPRESA"


def test_auth_me_unauthorized(client: TestClient):
    assert client.get("/auth/me").status_code == status.HTTP_401_UNAUTHORIZED


def test_permission_superuser_route(client: TestClient):
    @app.get("/test-admin-only")
    def admin_only_route(_user: Annotated[dict, Depends(require_superuser)]):
        return {"status": "ok"}

    headers_admin = auth_headers(client, "gestor@demo.com")
    assert client.get("/test-admin-only", headers=headers_admin).status_code == status.HTTP_200_OK

    headers_empresa = auth_headers(client, "empresa@demo.com")
    assert client.get("/test-admin-only", headers=headers_empresa).status_code == status.HTTP_403_FORBIDDEN


NOVO_REGISTRO = {
    "material_id": "papel",
    "periodo": "2026-09",
    "volume_total": 10.0,
    "percentual_reciclado": 50.0,
}


def test_protected_routes_require_authentication(client: TestClient):
    assert client.get("/registros/").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.post("/registros/", json=NOVO_REGISTRO).status_code == status.HTTP_401_UNAUTHORIZED


def test_company_creates_and_sees_only_own_records(client: TestClient):
    empresa = auth_headers(client, "empresa@demo.com")
    outra_empresa = auth_headers(client, "empresa2@demo.com")

    corpo = {**NOVO_REGISTRO, "empresa_id": "empresa-quixeramobim"}
    criado = client.post("/registros/", json=corpo, headers=empresa)
    assert criado.status_code == status.HTTP_201_CREATED
    assert criado.json()["empresa_id"] == "empresa-demo"

    proprios = client.get