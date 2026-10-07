import os
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends
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
    base_dir = os.path.dirname(os.path.dirname(__file__))
    con = sqlite3.connect("test_carbono.db")
    for script in ("create_db.sql", "seed_dev.sql"):
        script_path = os.path.join(base_dir, "src", script)
        if os.path.exists(script_path):
            with open(script_path, encoding="utf-8") as f:
                con.executescript(f.read())
    con.commit()
    con.close()

    yield

    if os.path.exists("test_carbono.db"):
        os.remove("test_carbono.db")


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


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
    assert response.status_code == 201
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
    assert response.status_code == 400
    assert response.json()["detail"] == "CNPJ já registado."


def test_register_company_duplicate_email(client: TestClient):
    payload = {
        "cnpj": "11223344000155",
        "email": "empresa@demo.com",  # Já presente no seed_dev.sql
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "E-mail já registado."


def test_register_company_email_used_by_prefeitura_admin(client: TestClient):
    payload = {
        "cnpj": "55667788000122",
        "email": "gestor@demo.com",  # E-mail de admin da prefeitura
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "E-mail já registado para um administrador da prefeitura."
    )


def test_register_company_nonexistent_prefeitura(client: TestClient):
    payload = {
        "cnpj": "99887766000111",
        "email": "empresa_sem_pref@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-inexistente-123",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "Prefeitura não encontrada."


def test_register_company_minimal_fields(client: TestClient):
    """
    Testa cadastro apenas com os campos obrigatórios
    (CNPJ, email, senha, prefeitura_id).
    """
    payload = {
        "cnpj": "98765432000111",
        "email": "minima@empresa.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    dados = response.json()
    assert dados["razao_social"] == f"Empresa {payload['cnpj']}"


# ============================================================================
# Testes de Autenticação (Login)
# ============================================================================


def test_login_prefeitura_success(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "gestor@demo.com", "senha": "demo123"},
    )
    assert response.status_code == 200
    dados = response.json()
    assert "access_token" in dados
    assert dados["token_type"] == "bearer"
    assert dados["user_type"] == "PREFEITURA"
    assert dados["email"] == "gestor@demo.com"
    assert dados["nome"] == "Gestor Demo"


def test_login_empresa_success(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "empresa@demo.com", "senha": "demo123"},
    )
    assert response.status_code == 200
    dados = response.json()
    assert "access_token" in dados
    assert dados["token_type"] == "bearer"
    assert dados["user_type"] == "EMPRESA"
    assert dados["status_vinculo"] == "APROVADA"


def test_login_invalid_password(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "gestor@demo.com", "senha": "senha_errada"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciais inválidas."


def test_login_nonexistent_email(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "inexistente@demo.com", "senha": "qualquer_senha"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciais inválidas."


def auth_headers(
    client: TestClient, email: str, senha: str = "demo123"
) -> dict[str, str]:
    resposta = client.post("/auth/login", json={"email": email, "senha": senha})
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


def test_login_company_confirmation_and_approval_flow(client: TestClient):
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
    assert response.status_code == 403
    assert response.json()["detail"]["codigo"] == "EMAIL_NAO_CONFIRMADO"

    aprovar = {"novo_status": "APROVADA"}
    url_status = f"/empresas/{empresa_id}/status"
    response = client.patch(url_status, json=aprovar, headers=prefeitura)
    assert response.status_code == 400

    db = TestingSessionLocal()
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    token = empresa.token_confirmacao_email
    db.close()

    response = client.get("/auth/confirm-email", params={"token": token})
    assert response.status_code == 200

    response = client.get("/auth/confirm-email", params={"token": token})
    assert response.status_code == 400

    response = client.post("/auth/login", json=login)
    assert response.status_code == 403
    assert response.json()["detail"]["codigo"] == "CADASTRO_PENDENTE"

    response = client.patch(url_status, json=aprovar, headers=prefeitura)
    assert response.status_code == 200

    response = client.post("/auth/login", json=login)
    assert response.status_code == 200
    assert response.json()["status_vinculo"] == "APROVADA"


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

    response = client.post(
        "/auth/login", json={"email": dados["email"], "senha": dados["senha"]}
    )
    assert response.status_code == 403
    detalhe = response.json()["detail"]
    assert detalhe["codigo"] == "CADASTRO_RECUSADO"
    assert "CNPJ fora da região" in detalhe["mensagem"]


def test_login_wrong_password_on_pending_company_stays_generic(client: TestClient):
    dados = {
        "cnpj": "33333333000133",
        "email": "pendente_senha@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    client.post("/auth/register", json=dados)

    response = client.post(
        "/auth/login", json={"email": dados["email"], "senha": "outra_senha"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciais inválidas."


def test_resend_confirmation_same_message(client: TestClient):
    dados = {
        "cnpj": "55555555000155",
        "email": "reenvio@teste.com",
        "senha": "password123",
        "prefeitura_id": "prefeitura-quixada",
    }
    client.post("/auth/register", json=dados)

    existente = client.post("/auth/resend-confirmation", json={"email": dados["email"]})
    inexistente = client.post(
        "/auth/resend-confirmation", json={"email": "ninguem@teste.com"}
    )
    assert existente.status_code == inexistente.status_code == 200
    assert existente.json() == inexistente.json()


# ============================================================================
# Testes do Endpoint /auth/me e Permissões
# ============================================================================


def test_auth_me_prefeitura(client: TestClient):
    login_resp = client.post(
        "/auth/login",
        json={"email": "gestor@demo.com", "senha": "demo123"},
    )
    token = login_resp.json()["access_token"]

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    dados = response.json()
    assert dados["email"] == "gestor@demo.com"
    assert dados["user_type"] == "PREFEITURA"
    assert dados["is_superuser"] is True
    assert dados["prefeitura_id"] == "prefeitura-quixada"


def test_auth_me_empresa(client: TestClient):
    login_resp = client.post(
        "/auth/login",
        json={"email": "empresa@demo.com", "senha": "demo123"},
    )
    token = login_resp.json()["access_token"]

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    dados = response.json()
    assert dados["email"] == "empresa@demo.com"
    assert dados["user_type"] == "EMPRESA"
    assert dados["is_superuser"] is False
    assert dados["status_vinculo"] == "APROVADA"


def test_auth_me_unauthorized(client: TestClient):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_permission_superuser_route(client: TestClient):
    @app.get("/test-admin-only")
    def admin_only_route(_user: Annotated[dict, Depends(require_superuser)]):
        return {"status": "ok"}

    login_admin = client.post(
        "/auth/login",
        json={"email": "gestor@demo.com", "senha": "demo123"},
    )
    admin_token = login_admin.json()["access_token"]
    resp_admin = client.get(
        "/test-admin-only",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_admin.status_code == 200

    login_empresa = client.post(
        "/auth/login",
        json={"email": "empresa@demo.com", "senha": "demo123"},
    )
    empresa_token = login_empresa.json()["access_token"]
    resp_empresa = client.get(
        "/test-admin-only",
        headers={"Authorization": f"Bearer {empresa_token}"},
    )
    assert resp_empresa.status_code == 403
    assert (
        resp_empresa.json()["detail"] == "Acesso restrito à Prefeitura (Superusuário)."
    )


NOVO_REGISTRO = {
    "material_id": "papel",
    "periodo": "2026-09",
    "volume_total": 10.0,
    "percentual_reciclado": 50.0,
}


def test_protected_routes_require_authentication(client: TestClient):
    assert client.get("/registros/").status_code == 401
    assert client.post("/registros/", json=NOVO_REGISTRO).status_code == 401
    assert client.get("/materiais/").status_code == 401
    assert client.get("/empresas/").status_code == 401
    aprovar = {"novo_status": "APROVADA"}
    resposta = client.patch("/empresas/empresa-demo/status", json=aprovar)
    assert resposta.status_code == 401


def test_company_creates_and_sees_only_own_records(client: TestClient):
    empresa = auth_headers(client, "empresa@demo.com")
    outra_empresa = auth_headers(client, "empresa2@demo.com")

    corpo = {**NOVO_REGISTRO, "empresa_id": "empresa-quixeramobim"}
    criado = client.post("/registros/", json=corpo, headers=empresa)
    assert criado.status_code == 201
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
    assert resposta.status_code == 403


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


def test_validation_restricted_to_prefeitura_of_same_city(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("src.services.services.obter_cotacao_dolar", lambda: 5.0)

    empresa_quixeramobim = auth_headers(client, "empresa2@demo.com")
    registro_id = client.post(
        "/registros/", json=NOVO_REGISTRO, headers=empresa_quixeramobim
    ).json()["id"]
    url = f"/registros/{registro_id}/validar"
    corpo = {"volume_validado": 8.0, "validador_id": "gestor-demo"}

    resposta = client.patch(url, json=corpo, headers=empresa_quixeramobim)
    assert resposta.status_code == 403

    quixada = auth_headers(client, "gestor@demo.com")
    resposta = client.patch(url, json=corpo, headers=quixada)
    assert resposta.status_code == 404

    quixeramobim = auth_headers(client, "gestor2@demo.com")
    resposta = client.patch(url, json=corpo, headers=quixeramobim)
    assert resposta.status_code == 200
    assert resposta.json()["status_validacao"] == "VALIDADO"
    assert resposta.json()["validador_id"] == "gestor-quixeramobim"


def test_material_creation_restricted_to_prefeitura(client: TestClient):
    material = {"categoria": "Madeira", "fator_emissaoipcc": 1.0}

    empresa = auth_headers(client, "empresa@demo.com")
    assert client.post("/materiais/", json=material, headers=empresa).status_code == 403

    prefeitura = auth_headers(client, "gestor@demo.com")
    resposta = client.post("/materiais/", json=material, headers=prefeitura)
    assert resposta.status_code == 201


def test_linked_companies_listing_restricted_to_own_city(client: TestClient):
    prefeitura = auth_headers(client, "gestor@demo.com")
    resposta = client.get("/empresas/", headers=prefeitura)
    assert resposta.status_code == 200
    empresas = resposta.json()
    assert "empresa-demo" in {e["id"] for e in empresas}
    assert {e["prefeitura_id"] for e in empresas} == {"prefeitura-quixada"}

    empresa = auth_headers(client, "empresa@demo.com")
    assert client.get("/empresas/", headers=empresa).status_code == 403


def test_prefeitura_cannot_change_company_from_other_city(client: TestClient):
    prefeitura = auth_headers(client, "gestor@demo.com")
    resposta = client.patch(
        "/empresas/empresa-quixeramobim/status",
        json={"novo_status": "RECUSADA", "motivo_recusa": "Fora do município"},
        headers=prefeitura,
    )
    assert resposta.status_code == 404


# ============================================================================
# User Story: Recuperação e Redefinição de Senha
# ============================================================================


GENERIC_FORGOT_MSG = (
    "Se o e-mail estiver cadastrado, as instruções e o token de "
    "redefinição foram enviados."
)


def test_forgot_password_registered_email(client: TestClient):
    """
    Critério 1 e 2:
    - Quando um e-mail cadastrado é informado, o sistema gera o token.
    - A mensagem exibida é a mensagem padrão genérica.
    """
    response = client.post(
        "/auth/forgot-password",
        json={"email": "gestor@demo.com"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == GENERIC_FORGOT_MSG

    # Verifica persistência do token no banco de testes
    db = TestingSessionLocal()
    token_entry = (
        db.query(TokenRedefinicaoSenha)
        .filter(TokenRedefinicaoSenha.email == "gestor@demo.com")
        .order_by(TokenRedefinicaoSenha.created_at.desc())
        .first()
    )
    assert token_entry is not None
    assert token_entry.utilizado is False
    assert token_entry.token is not None
    db.close()


def test_forgot_password_unregistered_email_same_message(client: TestClient):
    """
    Critério 2:
    - Por segurança, a mensagem é a mesma para e-mails não cadastrados.
    - Nenhum token é gerado no banco para o e-mail não cadastrado.
    """
    unregistered_email = "nao_existe@dominio.com"
    response = client.post(
        "/auth/forgot-password",
        json={"email": unregistered_email},
    )
    assert response.status_code == 200
    assert response.json()["message"] == GENERIC_FORGOT_MSG

    db = TestingSessionLocal()
    token_entry = (
        db.query(TokenRedefinicaoSenha)
        .filter(TokenRedefinicaoSenha.email == unregistered_email)
        .first()
    )
    assert token_entry is None
    db.close()


def test_reset_password_success_and_login(client: TestClient):
    """
    Critério 3 e 5:
    - Redefine a senha com token válido e senha que atende à política de complexidade.
    - Invalida o token após o primeiro uso.
    - Permite login com a nova senha e rejeita login com a senha antiga.
    """
    email = "empresa@demo.com"
    client.post("/auth/forgot-password", json={"email": email})

    db = TestingSessionLocal()
    token_entry = (
        db.query(TokenRedefinicaoSenha)
        .filter(
            TokenRedefinicaoSenha.email == email,
            TokenRedefinicaoSenha.utilizado.is_(False),
        )
        .order_by(TokenRedefinicaoSenha.created_at.desc())
        .first()
    )
    token = token_entry.token
    db.close()

    nova_senha = "NovaSenha@2026"
    reset_resp = client.post(
        "/auth/reset-password",
        json={"token": token, "nova_senha": nova_senha},
    )
    assert reset_resp.status_code == 200
    assert "Senha redefinida com sucesso" in reset_resp.json()["message"]

    # 1. Verifica no banco que o token foi marcado como utilizado
    db = TestingSessionLocal()
    recheck_token = (
        db.query(TokenRedefinicaoSenha)
        .filter(TokenRedefinicaoSenha.token == token)
        .first()
    )
    assert recheck_token.utilizado is True
    db.close()

    # 2. Testa login com a nova senha (deve ter sucesso)
    login_novo = client.post(
        "/auth/login",
        json={"email": email, "senha": nova_senha},
    )
    assert login_novo.status_code == 200
    assert "access_token" in login_novo.json()

    # 3. Testa login com a senha antiga (deve falhar com 401)
    login_antigo = client.post(
        "/auth/login",
        json={"email": email, "senha": "demo123"},
    )
    assert login_antigo.status_code == 401


def test_reset_password_single_use_invalidated(client: TestClient):
    """
    Critério 3:
    - O token é invalidado após seu primeiro uso e não pode ser reutilizado.
    """
    email = "gestor@demo.com"
    client.post("/auth/forgot-password", json={"email": email})

    db = TestingSessionLocal()
    token_entry = (
        db.query(TokenRedefinicaoSenha)
        .filter(
            TokenRedefinicaoSenha.email == email,
            TokenRedefinicaoSenha.utilizado.is_(False),
        )
        .order_by(TokenRedefinicaoSenha.created_at.desc())
        .first()
    )
    token = token_entry.token
    db.close()

    # Primeiro uso: sucesso
    res1 = client.post(
        "/auth/reset-password",
        json={"token": token, "nova_senha": "PrimeiraTroca@2026"},
    )
    assert res1.status_code == 200

    # Segundo uso do mesmo token: deve falhar
    res2 = client.post(
        "/auth/reset-password",
        json={"token": token, "nova_senha": "SegundaTroca@2026"},
    )
    assert res2.status_code == 400
    assert res2.json()["detail"] == "Token inválido ou já utilizado."


def test_reset_password_expired_token(client: TestClient):
    """
    Critério 3:
    - O token expira dentro do prazo definido e não é aceito se expirado.
    """
    db = TestingSessionLocal()
    token_expirado = "token_ja_expirado_123"
    data_passada = datetime.now(UTC) - timedelta(minutes=30)
    registro = TokenRedefinicaoSenha(
        email="gestor@demo.com",
        token=token_expirado,
        expiracao=data_passada,
        utilizado=False,
    )
    db.add(registro)
    db.commit()
    db.close()

    response = client.post(
        "/auth/reset-password",
        json={"token": token_expirado, "nova_senha": "SenhaForte@2026"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Token expirado. Solicite uma nova recuperação de senha."
    )


def test_reset_password_complexity_policy(client: TestClient):
    """
    Critério 5:
    - A nova senha deve atender à política de complexidade mínima:
      (mínimo 8 caracteres, maiúscula, minúscula, número e caractere especial).
    """
    valid_token = "token_para_teste_complexidade"
    db = TestingSessionLocal()
    db.add(
        TokenRedefinicaoSenha(
            email="gestor@demo.com",
            token=valid_token,
            expiracao=datetime.now(UTC) + timedelta(minutes=15),
            utilizado=False,
        )
    )
    db.commit()
    db.close()

    # 1. Menos de 8 caracteres
    r1 = client.post(
        "/auth/reset-password",
        json={"token": valid_token, "nova_senha": "Ab1!"},
    )
    assert r1.status_code == 400
    assert r1.json()["detail"] == "A nova senha deve ter no mínimo 8 caracteres."

    # 2. Sem letra maiúscula
    r2 = client.post(
        "/auth/reset-password",
        json={"token": valid_token, "nova_senha": "senhaforte@123"},
    )
    assert r2.status_code == 400
    assert (
        r2.json()["detail"]
        == "A nova senha deve conter pelo menos uma letra maiúscula."
    )

    # 3. Sem letra minúscula
    r3 = client.post(
        "/auth/reset-password",
        json={"token": valid_token, "nova_senha": "SENHAFORTE@123"},
    )
    assert r3.status_code == 400
    assert (
        r3.json()["detail"]
        == "A nova senha deve conter pelo menos uma letra minúscula."
    )

    # 4. Sem número
    r4 = client.post(
        "/auth/reset-password",
        json={"token": valid_token, "nova_senha": "SenhaForte@SemNum"},
    )
    assert r4.status_code == 400
    assert r4.json()["detail"] == "A nova senha deve conter pelo menos um número."

    # 5. Sem caractere especial
    r5 = client.post(
        "/auth/reset-password",
        json={"token": valid_token, "nova_senha": "SenhaForte1234"},
    )
    assert r5.status_code == 400
    assert (
        r5.json()["detail"]
        == "A nova senha deve conter pelo menos um caractere especial (!@#$%^&* etc.)."
    )


def test_reset_password_terminates_previous_active_sessions(client: TestClient):
    """
    Critério 4:
    - Após a redefinição de senha, todas as sessões ativas anteriores são encerradas.
    - Qualquer token emitido antes da redefinição é invalidado no endpoint /auth/me.
    """
    email = "gestor@demo.com"

    # 1. Login inicial (obter sessão ativa pré-reset)
    login_resp = client.post(
        "/auth/login",
        json={"email": email, "senha": "PrimeiraTroca@2026"},
    )
    assert login_resp.status_code == 200
    token_sessao_antiga = login_resp.json()["access_token"]

    # 2. Confirma que a sessão pré-reset funciona
    me_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token_sessao_antiga}"},
    )
    assert me_resp.status_code == 200

    # 3. Solicita recuperação e redefine a senha
    client.post("/auth/forgot-password", json={"email": email})
    db = TestingSessionLocal()
    token_entry = (
        db.query(TokenRedefinicaoSenha)
        .filter(
            TokenRedefinicaoSenha.email == email,
            TokenRedefinicaoSenha.utilizado.is_(False),
        )
        .order_by(TokenRedefinicaoSenha.created_at.desc())
        .first()
    )
    reset_token = token_entry.token
    db.close()

    nova_senha = "NovaSenhaDefinitiva@999"
    reset_resp = client.post(
        "/auth/reset-password",
        json={"token": reset_token, "nova_senha": nova_senha},
    )
    assert reset_resp.status_code == 200

    # 4. Tenta acessar com a sessão antiga: DEVE SER RECUSADA COM 401
    me_antigo_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token_sessao_antiga}"},
    )
    assert me_antigo_resp.status_code == 401
    assert (
        me_antigo_resp.json()["detail"]
        == "Sessão invalidada após alteração de senha. Faça login novamente."
    )

    # 5. Novo login com a nova senha funciona normalmente
    login_novo = client.post(
        "/auth/login",
        json={"email": email, "senha": nova_senha},
    )
    assert login_novo.status_code == 200
    novo_token = login_novo.json()["access_token"]

    me_novo_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {novo_token}"},
    )
    assert me_novo_resp.status_code == 200
