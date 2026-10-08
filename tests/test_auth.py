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
from src.models.models import Empresa, Registro, TokenRedefinicaoSenha
from src.schemas.enums import StatusValidacao
from src.services.email_service import email_service

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


def nova_empresa(cnpj: str, email: str, **extras: str) -> dict[str, str]:
    return {
        "cnpj": cnpj,
        "email": email,
        "senha": "password123",
        "razao_social": f"Empresa {cnpj} LTDA",
        "prefeitura_id": "prefeitura-quixada",
        **extras,
    }


def test_list_prefeituras_is_public(client: TestClient):
    response = client.get("/prefeituras/")
    assert response.status_code == status.HTTP_200_OK
    nomes = [p["nome"] for p in response.json()]
    assert nomes == sorted(nomes)
    assert {"Quixadá", "Quixeramobim"} <= set(nomes)


def test_register_company_success(client: TestClient, db: Session):
    payload = nova_empresa(
        "12.345.678/0001-95",
        "empresa_teste@valida.com",
        razao_social="Empresa Teste LTDA",
        nome_fantasia="Teste Corp",
        telefone="88999999999",
        endereco="Rua Exemplo, 123",
    )
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    dados = response.json()
    assert dados["cnpj"] == "12345678000195"
    assert dados["email"] == payload["email"]
    assert dados["razao_social"] == "Empresa Teste LTDA"
    assert dados["empresa_status"] == "AGUARDANDO VALIDACAO"

    empresa = db.query(Empresa).filter(Empresa.id == dados["id"]).first()
    assert empresa is not None
    assert empresa.pwd_hash != payload["senha"]
    assert empresa.pwd_hash.startswith("$2")


def test_register_company_requires_razao_social(client: TestClient):
    payload = nova_empresa("22334455000186", "sem_razao@empresa.com")
    del payload["razao_social"]
    assert client.post("/auth/register", json=payload).status_code == 422

    payload["razao_social"] = "   "
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Informe a razão social."


def test_register_company_invalid_cnpj(client: TestClient):
    for cnpj in ("12345678000199", "11111111111111", "123"):
        payload = nova_empresa(cnpj, f"cnpj_{cnpj}@empresa.com")
        response = client.post("/auth/register", json=payload)
        assert response.status_code == 422
        assert response.json()["detail"][0]["msg"] == "CNPJ inválido."


def test_register_company_invalid_email(client: TestClient):
    payload = nova_empresa("22334455000186", "email-sem-arroba")
    assert client.post("/auth/register", json=payload).status_code == 422


def test_register_company_duplicate_cnpj(client: TestClient):
    payload = nova_empresa("11.222.333/0001-81", "outro_email@empresa.com")
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "CNPJ já cadastrado."


def test_register_company_duplicate_email(client: TestClient):
    payload = nova_empresa("11223344000186", "empresa@demo.com")
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "E-mail já cadastrado."


def test_register_company_email_used_by_prefeitura_admin(client: TestClient):
    payload = nova_empresa("55667788000186", "gestor@demo.com")
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        response.json()["detail"]
        == "E-mail já cadastrado para um administrador da prefeitura."
    )


def test_register_company_nonexistent_prefeitura(client: TestClient):
    payload = nova_empresa(
        "99887766000105",
        "empresa_sem_pref@teste.com",
        prefeitura_id="prefeitura-inexistente-123",
    )
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Prefeitura não encontrada."


def test_register_company_minimal_fields(client: TestClient):
    payload = nova_empresa("98765432000198", "minima@empresa.com")
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    dados = response.json()
    assert dados["razao_social"] == payload["razao_social"]
    assert dados["nome_fantasia"] is None


# ============================================================================
# Testes de Autenticação (Login)
# ============================================================================


def test_login_prefeitura_success(client: TestClient):
    response = client.post(
        "/auth/login", json={"email": "gestor@demo.com", "senha": "demo123"}
    )
    assert response.status_code == status.HTTP_200_OK
    dados = response.json()
    assert "access_token" in dados
    assert dados["token_type"] == "bearer"
    assert dados["user_type"] == "PREFEITURA"
    assert dados["email"] == "gestor@demo.com"


def test_login_empresa_success(client: TestClient):
    response = client.post(
        "/auth/login", json={"email": "empresa@demo.com", "senha": "demo123"}
    )
    assert response.status_code == status.HTTP_200_OK
    dados = response.json()
    assert "access_token" in dados
    assert dados["user_type"] == "EMPRESA"
    assert dados["status_vinculo"] == "APROVADA"


def test_login_invalid_password(client: TestClient):
    response = client.post(
        "/auth/login", json={"email": "gestor@demo.com", "senha": "senha_errada"}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Credenciais inválidas."


def test_login_nonexistent_email(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "inexistente@demo.com", "senha": "qualquer_senha"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Credenciais inválidas."


def test_login_company_confirmation_and_approval_flow(client: TestClient, db: Session):
    prefeitura = auth_headers(client, "gestor@demo.com")
    dados = nova_empresa("33445566000186", "fluxo@teste.com")
    empresa_id = client.post("/auth/register", json=dados).json()["id"]
    login = {"email": dados["email"], "senha": dados["senha"]}

    response = client.post("/auth/login", json=login)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"]["codigo"] == "EMAIL_NAO_CONFIRMADO"

    aprovar = {"novo_status": "APROVADA"}
    url_status = f"/empresas/{empresa_id}/status"
    assert (
        client.patch(url_status, json=aprovar, headers=prefeitura).status_code
        == status.HTTP_400_BAD_REQUEST
    )

    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    assert empresa is not None
    token = empresa.token_confirmacao_email

    assert (
        client.get("/auth/confirm-email", params={"token": token}).status_code
        == status.HTTP_200_OK
    )
    assert (
        client.get("/auth/confirm-email", params={"token": token}).status_code
        == status.HTTP_400_BAD_REQUEST
    )

    assert (
        client.post("/auth/login", json=login).status_code == status.HTTP_403_FORBIDDEN
    )
    assert (
        client.patch(url_status, json=aprovar, headers=prefeitura).status_code
        == status.HTTP_200_OK
    )
    assert client.post("/auth/login", json=login).status_code == status.HTTP_200_OK


def test_login_refused_company_shows_reason(client: TestClient):
    dados = nova_empresa("66778899000186", "recusada@teste.com")
    empresa_id = client.post("/auth/register", json=dados).json()["id"]
    client.patch(
        f"/empresas/{empresa_id}/status",
        json={"novo_status": "RECUSADA", "motivo_recusa": "CNPJ fora da região"},
        headers=auth_headers(client, "gestor@demo.com"),
    )

    response = client.post(
        "/auth/login", json={"email": dados["email"], "senha": dados["senha"]}
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "CNPJ fora da região" in response.json()["detail"]["mensagem"]


def test_login_wrong_password_on_pending_company_stays_generic(client: TestClient):
    dados = nova_empresa("77889900000166", "pendente_senha@teste.com")
    assert client.post("/auth/register", json=dados).status_code == 201
    response = client.post(
        "/auth/login", json={"email": dados["email"], "senha": "outra_senha"}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Credenciais inválidas."


def test_resend_confirmation_same_message(client: TestClient):
    dados = nova_empresa("88990011000107", "reenvio@teste.com")
    client.post("/auth/register", json=dados)

    existente = client.post("/auth/resend-confirmation", json={"email": dados["email"]})
    inexistente = client.post(
        "/auth/resend-confirmation", json={"email": "ninguem@teste.com"}
    )

    assert existente.status_code == status.HTTP_200_OK
    assert existente.json() == inexistente.json()


# ============================================================================
# Testes do Endpoint /auth/me e Permissões
# ============================================================================


def test_auth_me_prefeitura(client: TestClient):
    headers = auth_headers(client, "gestor@demo.com")
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    dados = response.json()
    assert dados["user_type"] == "PREFEITURA"
    assert dados["is_superuser"] is True
    assert dados["prefeitura_id"] == "prefeitura-quixada"


def test_auth_me_empresa(client: TestClient):
    headers = auth_headers(client, "empresa@demo.com")
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    dados = response.json()
    assert dados["user_type"] == "EMPRESA"
    assert dados["is_superuser"] is False
    assert dados["status_vinculo"] == "APROVADA"


def test_auth_me_unauthorized(client: TestClient):
    assert client.get("/auth/me").status_code == status.HTTP_401_UNAUTHORIZED


def test_login_and_me_return_own_city_name(client: TestClient):
    login = client.post(
        "/auth/login", json={"email": "gestor2@demo.com", "senha": "demo123"}
    )
    assert login.json()["prefeitura_nome"] == "Quixeramobim"

    empresa = auth_headers(client, "empresa@demo.com")
    me = client.get("/auth/me", headers=empresa).json()
    assert me["prefeitura_nome"] == "Quixadá"


def test_permission_superuser_route(client: TestClient):
    @app.get("/test-admin-only")
    def admin_only_route(_user: Annotated[dict, Depends(require_superuser)]):
        return {"status": "ok"}

    headers_admin = auth_headers(client, "gestor@demo.com")
    assert (
        client.get("/test-admin-only", headers=headers_admin).status_code
        == status.HTTP_200_OK
    )

    headers_empresa = auth_headers(client, "empresa@demo.com")
    assert (
        client.get("/test-admin-only", headers=headers_empresa).status_code
        == status.HTTP_403_FORBIDDEN
    )


NOVO_REGISTRO = {
    "material_id": "papel",
    "periodo": "2026-09",
    "volume_total": 10.0,
    "percentual_reciclado": 50.0,
}


def test_protected_routes_require_authentication(client: TestClient):
    nao_autenticado = status.HTTP_401_UNAUTHORIZED
    assert client.get("/registros/").status_code == nao_autenticado
    assert client.post("/registros/", json=NOVO_REGISTRO).status_code == nao_autenticado
    assert client.get("/materiais/").status_code == nao_autenticado
    assert client.get("/empresas/").status_code == nao_autenticado
    aprovar = {"novo_status": "APROVADA"}
    resposta = client.patch("/empresas/empresa-demo/status", json=aprovar)
    assert resposta.status_code == nao_autenticado


def test_company_creates_and_sees_only_own_records(client: TestClient):
    empresa = auth_headers(client, "empresa@demo.com")
    outra_empresa = auth_headers(client, "empresa2@demo.com")

    corpo = {**NOVO_REGISTRO, "empresa_id": "empresa-quixeramobim"}
    criado = client.post("/registros/", json=corpo, headers=empresa)
    assert criado.status_code == status.HTTP_201_CREATED
    assert criado.json()["empresa_id"] == "empresa-demo"

    proprios = client.get("/registros/", headers=empresa).json()
    assert proprios
    assert {r["empresa_id"] for r in proprios} == {"empresa-demo"}

    alheios = client.get(
        "/registros/", params={"empresa_id": "empresa-demo"}, headers=outra_empresa
    ).json()
    assert alheios == []


def test_prefeitura_cannot_create_records(client: TestClient):
    prefeitura = auth_headers(client, "gestor@demo.com")
    resposta = client.post("/registros/", json=NOVO_REGISTRO, headers=prefeitura)
    assert resposta.status_code == status.HTTP_403_FORBIDDEN


def test_prefeitura_sees_only_records_from_own_city(client: TestClient):
    empresa_quixeramobim = auth_headers(client, "empresa2@demo.com")
    registro_id = client.post(
        "/registros/", json=NOVO_REGISTRO, headers=empresa_quixeramobim
    ).json()["id"]

    quixada = auth_headers(client, "gestor@demo.com")
    vistos_quixada = client.get("/registros/", headers=quixada).json()
    assert registro_id not in {r["id"] for r in vistos_quixada}
    assert "empresa-quixeramobim" not in {r["empresa_id"] for r in vistos_quixada}

    quixeramobim = auth_headers(client, "gestor2@demo.com")
    vistos_quixeramobim = client.get("/registros/", headers=quixeramobim).json()
    assert registro_id in {r["id"] for r in vistos_quixeramobim}


def test_refused_record_status_is_accepted_by_database(db: Session):
    registro = Registro(
        empresa_id="empresa-demo",
        material_id="papel",
        periodo="2026-09",
        volume_total_original=5.0,
        percentual_reciclado=40.0,
        status_validacao=StatusValidacao.RECUSADA,
        motivo_rejeicao="Volume incompatível com a coleta",
    )
    db.add(registro)
    db.commit()
    db.expire_all()

    salvo = db.query(Registro).filter(Registro.id == registro.id).first()
    assert salvo is not None
    assert salvo.status_validacao == StatusValidacao.RECUSADA


def test_validation_restricted_to_prefeitura_of_same_city(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "src.services.services.obter_cotacao_dolar", lambda *args, **kwargs: 5.0
    )

    empresa_quixeramobim = auth_headers(client, "empresa2@demo.com")
    registro_id = client.post(
        "/registros/", json=NOVO_REGISTRO, headers=empresa_quixeramobim
    ).json()["id"]
    url = f"/registros/{registro_id}/validar"
    corpo = {"volume_validado": 8.0, "validador_id": "gestor-demo"}

    resposta = client.patch(url, json=corpo, headers=empresa_quixeramobim)
    assert resposta.status_code == status.HTTP_403_FORBIDDEN

    quixada = auth_headers(client, "gestor@demo.com")
    resposta = client.patch(url, json=corpo, headers=quixada)
    assert resposta.status_code == status.HTTP_404_NOT_FOUND

    quixeramobim = auth_headers(client, "gestor2@demo.com")
    resposta = client.patch(url, json=corpo, headers=quixeramobim)
    assert resposta.status_code == status.HTTP_200_OK
    assert resposta.json()["status_validacao"] == "VALIDADO"
    assert resposta.json()["validador_id"] == "gestor-quixeramobim"


def test_material_creation_restricted_to_prefeitura(client: TestClient):
    material = {"categoria": "Madeira", "fator_emissaoipcc": 1.0}

    empresa = auth_headers(client, "empresa@demo.com")
    resposta = client.post("/materiais/", json=material, headers=empresa)
    assert resposta.status_code == status.HTTP_403_FORBIDDEN

    prefeitura = auth_headers(client, "gestor@demo.com")
    resposta = client.post("/materiais/", json=material, headers=prefeitura)
    assert resposta.status_code == status.HTTP_201_CREATED


def test_linked_companies_listing_restricted_to_own_city(client: TestClient):
    prefeitura = auth_headers(client, "gestor@demo.com")
    resposta = client.get("/empresas/", headers=prefeitura)
    assert resposta.status_code == status.HTTP_200_OK
    empresas = resposta.json()
    assert "empresa-demo" in {e["id"] for e in empresas}
    assert {e["prefeitura_id"] for e in empresas} == {"prefeitura-quixada"}
    demo = next(e for e in empresas if e["id"] == "empresa-demo")
    assert demo["email_confirmado"] is True

    empresa = auth_headers(client, "empresa@demo.com")
    resposta = client.get("/empresas/", headers=empresa)
    assert resposta.status_code == status.HTTP_403_FORBIDDEN


def test_prefeitura_cannot_change_company_from_other_city(client: TestClient):
    prefeitura = auth_headers(client, "gestor@demo.com")
    resposta = client.patch(
        "/empresas/empresa-quixeramobim/status",
        json={"novo_status": "RECUSADA", "motivo_recusa": "Fora do município"},
        headers=prefeitura,
    )
    assert resposta.status_code == status.HTTP_404_NOT_FOUND

    resposta = client.patch(
        "/empresas/empresa-quixeramobim",
        json={"nome_fantasia": "Outro nome"},
        headers=prefeitura,
    )
    assert resposta.status_code == status.HTTP_404_NOT_FOUND


def test_company_status_statistics_restricted_to_own_city(client: TestClient):
    empresa = auth_headers(client, "empresa@demo.com")
    resposta = client.get("/empresas/estatisticas/status", headers=empresa)
    assert resposta.status_code == status.HTTP_403_FORBIDDEN

    prefeitura = auth_headers(client, "gestor2@demo.com")
    resposta = client.get("/empresas/estatisticas/status", headers=prefeitura)
    assert resposta.status_code == status.HTTP_200_OK
    assert resposta.json() == {"APROVADA": 1}


# ============================================================================
# Testes de Edição dos Dados Cadastrais da Empresa
# ============================================================================


def token_de_confirmacao(db: Session, empresa_id: str) -> str:
    db.expire_all()
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    assert empresa is not None
    assert empresa.token_confirmacao_email
    return empresa.token_confirmacao_email


def criar_empresa_aprovada(
    client: TestClient, db: Session, cnpj: str, email: str
) -> tuple[str, dict[str, str]]:
    dados = nova_empresa(cnpj, email)
    empresa_id = client.post("/auth/register", json=dados).json()["id"]
    token = token_de_confirmacao(db, empresa_id)
    client.get("/auth/confirm-email", params={"token": token})
    aprovada = client.patch(
        f"/empresas/{empresa_id}/status",
        json={"novo_status": "APROVADA"},
        headers=auth_headers(client, "gestor@demo.com"),
    )
    assert aprovada.status_code == status.HTTP_200_OK
    return empresa_id, auth_headers(client, email, dados["senha"])


def test_company_edits_own_data_with_history(client: TestClient, db: Session):
    empresa_id, empresa = criar_empresa_aprovada(
        client, db, "31415926000171", "edita@teste.com"
    )
    assert client.get("/empresas/me", headers=empresa).json()["id"] == empresa_id

    alteracoes = {
        "razao_social": "Nova Razão LTDA",
        "nome_fantasia": "Nova Fantasia",
        "telefone": "88988887777",
        "endereco": "Rua Nova, 10",
    }
    resposta = client.patch("/empresas/me", json=alteracoes, headers=empresa)
    assert resposta.status_code == status.HTTP_200_OK
    dados = resposta.json()
    for campo, valor in alteracoes.items():
        assert dados[campo] == valor

    historico = client.get("/empresas/me/historico", headers=empresa).json()
    assert {h["campo"] for h in historico} == set(alteracoes)
    razao = next(h for h in historico if h["campo"] == "razao_social")
    assert razao["valor_anterior"] == "Empresa 31415926000171 LTDA"
    assert razao["valor_novo"] == "Nova Razão LTDA"
    assert razao["autor_id"] == empresa_id
    assert razao["autor_nome"]
    assert razao["created_at"]


def test_company_cannot_change_cnpj_after_validation(client: TestClient, db: Session):
    _, empresa = criar_empresa_aprovada(
        client, db, "27182818000129", "cnpj_fixo@teste.com"
    )
    resposta = client.patch(
        "/empresas/me", json={"cnpj": "11.444.777/0001-61"}, headers=empresa
    )
    assert resposta.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        resposta.json()["detail"]
        == "O CNPJ não pode ser alterado após a validação do cadastro."
    )
    assert client.get("/empresas/me", headers=empresa).json()["cnpj"] == (
        "27182818000129"
    )


def test_company_email_change_requires_confirmation(client: TestClient, db: Session):
    empresa_id, empresa = criar_empresa_aprovada(
        client, db, "16180339000157", "email_antigo@teste.com"
    )

    resposta = client.patch(
        "/empresas/me", json={"email": "email_novo@teste.com"}, headers=empresa
    )
    assert resposta.status_code == status.HTTP_200_OK
    assert resposta.json()["email"] == "email_antigo@teste.com"
    assert resposta.json()["email_pendente"] == "email_novo@teste.com"

    senha = "password123"
    login_antigo = {"email": "email_antigo@teste.com", "senha": senha}
    login_novo = {"email": "email_novo@teste.com", "senha": senha}
    assert client.post("/auth/login", json=login_antigo).status_code == 200
    assert client.post("/auth/login", json=login_novo).status_code == 401

    token = token_de_confirmacao(db, empresa_id)
    confirmacao = client.get("/auth/confirm-email", params={"token": token})
    assert confirmacao.status_code == status.HTTP_200_OK

    assert client.post("/auth/login", json=login_antigo).status_code == 401
    assert client.post("/auth/login", json=login_novo).status_code == 200

    dados = client.get("/empresas/me", headers=empresa).json()
    assert dados["email"] == "email_novo@teste.com"
    assert dados["email_pendente"] is None

    historico = client.get("/empresas/me/historico", headers=empresa).json()
    troca = next(h for h in historico if h["campo"] == "email")
    assert troca["valor_anterior"] == "email_antigo@teste.com"
    assert troca["valor_novo"] == "email_novo@teste.com"
    assert any(h["campo"] == "email_pendente" for h in historico)


def test_company_email_change_rejects_email_in_use(client: TestClient, db: Session):
    _, empresa = criar_empresa_aprovada(
        client, db, "14142135000104", "email_livre@teste.com"
    )
    resposta = client.patch(
        "/empresas/me", json={"email": "gestor2@demo.com"}, headers=empresa
    )
    assert resposta.status_code == status.HTTP_400_BAD_REQUEST
    assert resposta.json()["detail"] == "E-mail já cadastrado."


def test_company_data_routes_restricted_to_companies(client: TestClient):
    prefeitura = auth_headers(client, "gestor2@demo.com")
    assert client.get("/empresas/me", headers=prefeitura).status_code == 403
    resposta = client.patch("/empresas/me", json={"telefone": "1"}, headers=prefeitura)
    assert resposta.status_code == status.HTTP_403_FORBIDDEN
    assert client.get("/empresas/me").status_code == 401


def test_prefeitura_edit_follows_rules_and_records_author(client: TestClient):
    prefeitura = auth_headers(client, "gestor2@demo.com")
    resposta = client.patch(
        "/empresas/empresa-quixeramobim",
        json={"telefone": "88912345678", "empresa_status": "RECUSADA"},
        headers=prefeitura,
    )
    assert resposta.status_code == status.HTTP_200_OK
    assert resposta.json()["telefone"] == "88912345678"
    assert resposta.json()["empresa_status"] == "APROVADA"

    empresa = auth_headers(client, "empresa2@demo.com")
    historico = client.get("/empresas/me/historico", headers=empresa).json()
    telefone = next(h for h in historico if h["campo"] == "telefone")
    assert telefone["autor_id"] == "gestor-quixeramobim"
    assert telefone["autor_nome"] == "Gestor Quixeramobim"


# ============================================================================
# User Story: Recuperação e Redefinição de Senha
# ============================================================================


GENERIC_FORGOT_MSG = (
    "Se o e-mail estiver cadastrado, as instruções e o token de "
    "redefinição foram enviados."
)


def ultimo_token_de_redefinicao(db: Session, email: str) -> str:
    db.expire_all()
    registro = (
        db.query(TokenRedefinicaoSenha)
        .filter(
            TokenRedefinicaoSenha.email == email,
            TokenRedefinicaoSenha.utilizado.is_(False),
        )
        .order_by(TokenRedefinicaoSenha.created_at.desc())
        .first()
    )
    assert registro is not None
    return registro.token


def test_forgot_password_registered_email(client: TestClient, db: Session):
    """
    Critério 1 e 2:
    - Quando um e-mail cadastrado é informado, o sistema gera o token.
    - A mensagem exibida é a mensagem padrão genérica.
    """
    response = client.post("/auth/forgot-password", json={"email": "gestor@demo.com"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == GENERIC_FORGOT_MSG
    assert ultimo_token_de_redefinicao(db, "gestor@demo.com")


def test_forgot_password_unregistered_email_same_message(
    client: TestClient, db: Session
):
    """
    Critério 2:
    - Por segurança, a mensagem é a mesma para e-mails não cadastrados.
    - Nenhum token é gerado no banco para o e-mail não cadastrado.
    """
    email = "nao_existe@dominio.com"
    response = client.post("/auth/forgot-password", json={"email": email})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == GENERIC_FORGOT_MSG

    token = (
        db.query(TokenRedefinicaoSenha)
        .filter(TokenRedefinicaoSenha.email == email)
        .first()
    )
    assert token is None


def test_reset_password_success_and_login(client: TestClient, db: Session):
    """
    Critério 3 e 5:
    - Redefine a senha com token válido e senha que atende à política.
    - Invalida o token após o primeiro uso.
    - Permite login com a nova senha e rejeita login com a senha antiga.
    """
    email = "empresa@demo.com"
    client.post("/auth/forgot-password", json={"email": email})
    token = ultimo_token_de_redefinicao(db, email)

    nova_senha = "NovaSenha@2026"
    resposta = client.post(
        "/auth/reset-password", json={"token": token, "nova_senha": nova_senha}
    )
    assert resposta.status_code == status.HTTP_200_OK
    assert "Senha redefinida com sucesso" in resposta.json()["message"]

    db.expire_all()
    usado = (
        db.query(TokenRedefinicaoSenha)
        .filter(TokenRedefinicaoSenha.token == token)
        .first()
    )
    assert usado is not None
    assert usado.utilizado is True

    login_novo = client.post("/auth/login", json={"email": email, "senha": nova_senha})
    assert login_novo.status_code == status.HTTP_200_OK

    login_antigo = client.post("/auth/login", json={"email": email, "senha": "demo123"})
    assert login_antigo.status_code == status.HTTP_401_UNAUTHORIZED


def test_reset_password_single_use_invalidated(client: TestClient, db: Session):
    """
    Critério 3:
    - O token é invalidado após seu primeiro uso e não pode ser reutilizado.
    """
    email = "gestor@demo.com"
    client.post("/auth/forgot-password", json={"email": email})
    token = ultimo_token_de_redefinicao(db, email)

    primeira = client.post(
        "/auth/reset-password",
        json={"token": token, "nova_senha": "PrimeiraTroca@2026"},
    )
    assert primeira.status_code == status.HTTP_200_OK

    segunda = client.post(
        "/auth/reset-password",
        json={"token": token, "nova_senha": "SegundaTroca@2026"},
    )
    assert segunda.status_code == status.HTTP_400_BAD_REQUEST
    assert segunda.json()["detail"] == "Token inválido ou já utilizado."


def test_reset_password_expired_token(client: TestClient, db: Session):
    """
    Critério 3:
    - O token expira dentro do prazo definido e não é aceito se expirado.
    """
    token_expirado = "token_ja_expirado_123"
    db.add(
        TokenRedefinicaoSenha(
            email="gestor@demo.com",
            token=token_expirado,
            expiracao=datetime.now(UTC) - timedelta(minutes=30),
            utilizado=False,
        )
    )
    db.commit()

    resposta = client.post(
        "/auth/reset-password",
        json={"token": token_expirado, "nova_senha": "SenhaForte@2026"},
    )
    assert resposta.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        resposta.json()["detail"]
        == "Token expirado. Solicite uma nova recuperação de senha."
    )


def test_reset_password_complexity_policy(client: TestClient, db: Session):
    """
    Critério 4:
    - A nova senha deve atender à política de complexidade mínima:
      (mínimo 8 caracteres, maiúscula, minúscula, número e caractere especial).
    """
    token = "token_para_teste_complexidade"
    db.add(
        TokenRedefinicaoSenha(
            email="gestor@demo.com",
            token=token,
            expiracao=datetime.now(UTC) + timedelta(minutes=15),
            utilizado=False,
        )
    )
    db.commit()

    casos = [
        ("Ab1!", "A nova senha deve ter no mínimo 8 caracteres."),
        (
            "senhaforte@123",
            "A nova senha deve conter pelo menos uma letra maiúscula.",
        ),
        (
            "SENHAFORTE@123",
            "A nova senha deve conter pelo menos uma letra minúscula.",
        ),
        ("SenhaForte@SemNum", "A nova senha deve conter pelo menos um número."),
        (
            "SenhaForte1234",
            "A nova senha deve conter pelo menos um caractere especial "
            "(!@#$%^&* etc.).",
        ),
    ]
    for senha, mensagem in casos:
        resposta = client.post(
            "/auth/reset-password", json={"token": token, "nova_senha": senha}
        )
        assert resposta.status_code == status.HTTP_400_BAD_REQUEST
        assert resposta.json()["detail"] == mensagem


def test_reset_password_terminates_previous_active_sessions(
    client: TestClient, db: Session
):
    """
    Critério 5:
    - Após a redefinição de senha, todas as sessões ativas anteriores são encerradas.
    - Qualquer token emitido antes da redefinição é invalidado no endpoint /auth/me.
    """
    email = "gestor@demo.com"
    sessao_antiga = auth_headers(client, email, "PrimeiraTroca@2026")
    assert client.get("/auth/me", headers=sessao_antiga).status_code == 200

    client.post("/auth/forgot-password", json={"email": email})
    token = ultimo_token_de_redefinicao(db, email)

    nova_senha = "NovaSenhaDefinitiva@999"
    resposta = client.post(
        "/auth/reset-password", json={"token": token, "nova_senha": nova_senha}
    )
    assert resposta.status_code == status.HTTP_200_OK

    me_antigo = client.get("/auth/me", headers=sessao_antiga)
    assert me_antigo.status_code == status.HTTP_401_UNAUTHORIZED
    assert (
        me_antigo.json()["detail"]
        == "Sessão invalidada após alteração de senha. Faça login novamente."
    )

    sessao_nova = auth_headers(client, email, nova_senha)
    assert client.get("/auth/me", headers=sessao_nova).status_code == 200


# ============================================================================
# Testes do Envio de E-mails
# ============================================================================


@pytest.fixture
def emails_enviados(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    enviados: list[dict[str, str]] = []

    def registrar(**email: str) -> bool:
        enviados.append(email)
        return True

    monkeypatch.setattr(email_service, "enviar", registrar)
    return enviados


def test_forgot_password_sends_token_only_to_registered_email(
    client: TestClient, db: Session, emails_enviados: list[dict[str, str]]
):
    client.post("/auth/forgot-password", json={"email": "empresa2@demo.com"})
    client.post("/auth/forgot-password", json={"email": "ninguem@dominio.com"})

    assert [e["destinatario"] for e in emails_enviados] == ["empresa2@demo.com"]
    token = ultimo_token_de_redefinicao(db, "empresa2@demo.com")
    assert token in emails_enviados[0]["corpo"]
    assert "15 minutos" in emails_enviados[0]["corpo"]


def test_register_sends_confirmation_link(
    client: TestClient, db: Session, emails_enviados: list[dict[str, str]]
):
    dados = nova_empresa("13579246000101", "link@teste.com")
    empresa_id = client.post("/auth/register", json=dados).json()["id"]
    token = token_de_confirmacao(db, empresa_id)

    assert [e["destinatario"] for e in emails_enviados] == ["link@teste.com"]
    assert f"/auth/confirm-email?token={token}" in emails_enviados[0]["corpo"]


def test_email_service_sends_through_configured_smtp(
    monkeypatch: pytest.MonkeyPatch,
):
    chamadas: list[tuple[str, ...]] = []

    class SmtpFalso:
        def __init__(self, host: str, porta: int, timeout: int):
            chamadas.append(("conectar", host, str(porta)))

        def __enter__(self) -> "SmtpFalso":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:
            chamadas.append(("starttls",))

        def login(self, usuario: str, senha: str) -> None:
            chamadas.append(("login", usuario, senha))

        def send_message(self, mensagem) -> None:
            chamadas.append(("enviar", mensagem["To"], mensagem["Subject"]))

    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "arclear@exemplo.com")
    monkeypatch.setenv("SMTP_PASSWORD", "segredo")
    monkeypatch.setattr("src.services.email_service.smtplib.SMTP", SmtpFalso)

    assert email_service.enviar("destino@teste.com", "Assunto", "Corpo") is True
    assert chamadas == [
        ("conectar", "smtp.exemplo.com", "587"),
        ("starttls",),
        ("login", "arclear@exemplo.com", "segredo"),
        ("enviar", "destino@teste.com", "Assunto"),
    ]


def test_email_service_failure_does_not_break_request(
    monkeypatch: pytest.MonkeyPatch,
):
    def falhar(*args: object, **kwargs: object) -> None:
        raise OSError("servidor fora do ar")

    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr("src.services.email_service.smtplib.SMTP", falhar)

    assert email_service.enviar("destino@teste.com", "Assunto", "Corpo") is False
