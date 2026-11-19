from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.models.models import Empresa
from src.schemas.validacao import digito_verificador_cnpj

HOJE = date.today()
PERIODO_ATUAL = f"{HOJE.year}-{HOJE.month:02d}"
PROXIMO = (HOJE.year + HOJE.month // 12, HOJE.month % 12 + 1)
PERIODO_FUTURO = f"{PROXIMO[0]}-{PROXIMO[1]:02d}"


def cabecalho(client: TestClient, email: str, senha: str = "demo123") -> dict:
    resposta = client.post("/auth/login", json={"email": email, "senha": senha})
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


def cnpj_valido(base: str) -> str:
    primeiro = digito_verificador_cnpj(base)
    return base + primeiro + digito_verificador_cnpj(base + primeiro)


def cadastro(cnpj: str, email: str, **extras) -> dict:
    return {
        "cnpj": cnpj,
        "email": email,
        "senha": "Senha@123",
        "razao_social": "Empresa de Teste LTDA",
        "prefeitura_id": "prefeitura-quixada",
        **extras,
    }


def lancamento(**extras) -> dict:
    return {
        "material_id": "papel",
        "periodo": PERIODO_ATUAL,
        "volume_total": 10.0,
        "percentual_reciclado": 50.0,
        **extras,
    }


def test_detalhe_da_empresa_exige_login_e_respeita_o_municipio(client: TestClient):
    assert client.get("/empresas/empresa-demo").status_code == 401

    gestor = cabecalho(client, "gestor@demo.com")
    gestor_vizinho = cabecalho(client, "gestor2@demo.com")
    empresa = cabecalho(client, "empresa@demo.com")

    assert client.get("/empresas/empresa-demo", headers=gestor).status_code == 200
    assert (
        client.get("/empresas/empresa-demo", headers=gestor_vizinho).status_code == 404
    )
    assert client.get("/empresas/empresa-demo", headers=empresa).status_code == 200
    assert (
        client.get("/empresas/empresa-quixeramobim", headers=empresa).status_code == 404
    )


def test_lancamento_exige_login_e_ignora_empresa_do_corpo(client: TestClient):
    assert (
        client.post(
            "/registros/", json=lancamento(empresa_id="empresa-demo")
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/registros/",
            json=lancamento(empresa_id="empresa-demo"),
            headers={"Authorization": "Bearer token-invalido"},
        ).status_code
        == 401
    )

    resposta = client.post(
        "/registros/",
        json=lancamento(empresa_id="empresa-quixeramobim"),
        headers=cabecalho(client, "empresa@demo.com"),
    )
    assert resposta.status_code == 201
    assert resposta.json()["empresa_id"] == "empresa-demo"


def test_email_nao_diferencia_maiusculas(client: TestClient):
    for email in ("Empresa@Demo.com", "EMPRESA@demo.com", "Gestor@Demo.com"):
        resposta = client.post(
            "/auth/register",
            json=cadastro(cnpj_valido("314445550001"), email),
        )
        assert resposta.status_code == 400, email

    assert (
        client.post(
            "/auth/login", json={"email": "EMPRESA@DEMO.COM", "senha": "demo123"}
        ).status_code
        == 200
    )

    resposta = client.post(
        "/auth/register",
        json=cadastro(cnpj_valido("320000000001"), "Fulano.Silva@Empresa.com"),
    )
    assert resposta.status_code == 201
    assert resposta.json()["email"] == "fulano.silva@empresa.com"

    resposta = client.post(
        "/auth/login",
        json={"email": "fulano.silva@EMPRESA.com", "senha": "Senha@123"},
    )
    assert resposta.status_code == 403
    assert resposta.json()["detail"]["codigo"] == "EMAIL_NAO_CONFIRMADO"


def test_materiais_ficam_no_municipio_que_os_cadastrou(client: TestClient):
    gestor = cabecalho(client, "gestor@demo.com")
    gestor_vizinho = cabecalho(client, "gestor2@demo.com")
    empresa_vizinha = cabecalho(client, "empresa2@demo.com")

    criado = client.post(
        "/materiais/",
        json={"categoria": "Madeira", "fator_emissaoipcc": 1.25},
        headers=gestor,
    )
    assert criado.status_code == 201
    material = criado.json()
    assert material["prefeitura_id"] == "prefeitura-quixada"

    ids_vizinho = {
        m["id"] for m in client.get("/materiais/", headers=gestor_vizinho).json()
    }
    assert material["id"] not in ids_vizinho
    assert {"papel", "plastico", "vidro", "metal"} <= ids_vizinho

    url = f"/materiais/{material['id']}"
    assert client.get(url, headers=gestor_vizinho).status_code == 404
    assert (
        client.patch(
            url, json={"fator_emissaoipcc": 9}, headers=gestor_vizinho
        ).status_code
        == 404
    )
    assert client.delete(url, headers=gestor_vizinho).status_code == 404
    assert (
        client.post(
            "/registros/",
            json=lancamento(material_id=material["id"]),
            headers=empresa_vizinha,
        ).status_code
        == 400
    )

    mesmo_nome = client.post(
        "/materiais/",
        json={"categoria": "Madeira", "fator_emissaoipcc": 2},
        headers=gestor_vizinho,
    )
    assert mesmo_nome.status_code == 201

    for metodo, corpo in (("patch", {"fator_emissaoipcc": 9.99}), ("delete", None)):
        resposta = client.request(
            metodo, "/materiais/papel", json=corpo, headers=gestor
        )
        assert resposta.status_code == 403
    assert (
        client.get("/materiais/papel", headers=gestor).json()["fator_emissaoipcc"]
        == 1.0
    )


def test_regras_dos_campos_do_material(client: TestClient):
    gestor = cabecalho(client, "gestor@demo.com")
    invalidos = [
        {"categoria": "A", "fator_emissaoipcc": 1},
        {"categoria": "M" * 61, "fator_emissaoipcc": 1},
        {"categoria": "Isopor", "fator_emissaoipcc": 0},
        {"categoria": "Isopor", "fator_emissaoipcc": 1.234},
    ]
    for corpo in invalidos:
        resposta = client.post("/materiais/", json=corpo, headers=gestor)
        assert resposta.status_code == 422, corpo

    assert (
        client.post(
            "/materiais/",
            json={"categoria": "M" * 60, "fator_emissaoipcc": 0.01},
            headers=gestor,
        ).status_code
        == 201
    )


def test_gestor_nao_lanca_periodo_futuro(client: TestClient):
    gestor = cabecalho(client, "gestor@demo.com")
    resposta = client.post(
        "/registros/gestor",
        json=lancamento(empresa_id="empresa-demo", periodo=PERIODO_FUTURO),
        headers=gestor,
    )
    assert resposta.status_code == 422
    assert resposta.json()["detail"][0]["msg"] == "O período não pode estar no futuro."


def test_limites_de_periodo_e_volume(client: TestClient):
    empresa = cabecalho(client, "empresa@demo.com")
    for extras in ({"periodo": "1999-12"}, {"volume_total": 100_001}):
        resposta = client.post(
            "/registros/", json=lancamento(**extras), headers=empresa
        )
        assert resposta.status_code == 422, extras
    assert (
        client.post(
            "/registros/", json=lancamento(volume_total=100_000), headers=empresa
        ).status_code
        == 201
    )


def test_motivo_da_rejeicao_tem_limites(client: TestClient):
    empresa = cabecalho(client, "empresa@demo.com")
    gestor = cabecalho(client, "gestor@demo.com")
    registro_id = client.post("/registros/", json=lancamento(), headers=empresa).json()[
        "id"
    ]
    url = f"/registros/{registro_id}/rejeitar"

    assert client.patch(url, json={}, headers=gestor).status_code == 400
    for motivo in ("abc", "m" * 501):
        resposta = client.patch(url, json={"motivo_rejeicao": motivo}, headers=gestor)
        assert resposta.status_code == 422
    assert (
        client.patch(
            f"/registros/{registro_id}/status",
            json={"status_validacao": "REJEITADO", "motivo": "abc"},
            headers=gestor,
        ).status_code
        == 422
    )
    assert (
        client.patch(
            url, json={"motivo_rejeicao": "Volume não confere"}, headers=gestor
        ).status_code
        == 200
    )


def test_erros_de_validacao_em_portugues_e_sem_erro_500(client: TestClient):
    resposta = client.post(
        "/auth/register",
        json=cadastro(cnpj_valido("330000000001"), "nome@dominio.com."),
    )
    assert resposta.status_code == 422
    assert resposta.json()["detail"][0]["msg"] == "Informe um e-mail válido."

    resposta = client.post(
        "/registros/",
        content=(
            '{"material_id": "papel", "periodo": "'
            + PERIODO_ATUAL
            + '", "volume_total": NaN, "percentual_reciclado": 50}'
        ),
        headers={
            **cabecalho(client, "empresa@demo.com"),
            "Content-Type": "application/json",
        },
    )
    assert resposta.status_code == 422
    assert "input" not in resposta.json()["detail"][0]


def test_periodo_invalido_nas_consultas(client: TestClient):
    gestor = cabecalho(client, "gestor@demo.com")
    for url in (
        "/empresas/estatisticas/ranking",
        "/dashboard/",
        "/relatorios/",
        "/registros/",
        "/registros/estatisticas/resumo",
    ):
        resposta = client.get(url, params={"periodo": "abc"}, headers=gestor)
        assert resposta.status_code == 422, url
        assert (
            resposta.json()["detail"][0]["msg"]
            == "Informe o período no formato AAAA-MM."
        )


def test_cnpj_alfanumerico(client: TestClient):
    resposta = client.post(
        "/auth/register",
        json=cadastro("12.abc.345/01de-35", "alfanumerico@empresa.com"),
    )
    assert resposta.status_code == 201
    assert resposta.json()["cnpj"] == "12ABC34501DE35"

    resposta = client.post(
        "/auth/register",
        json=cadastro("12ABC34501DE36", "alfanumerico2@empresa.com"),
    )
    assert resposta.status_code == 422


def test_link_de_confirmacao_aberto_no_navegador(client: TestClient, db: Session):
    empresa_id = client.post(
        "/auth/register",
        json=cadastro(cnpj_valido("340000000001"), "pagina@empresa.com"),
    ).json()["id"]
    db.expire_all()
    token = db.get(Empresa, empresa_id).token_confirmacao_email

    resposta = client.get(
        "/auth/confirm-email",
        params={"token": token},
        headers={"Accept": "text/html"},
    )
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    assert "E-mail confirmado" in resposta.text

    resposta = client.get(
        "/auth/confirm-email",
        params={"token": token},
        headers={"Accept": "text/html"},
    )
    assert resposta.status_code == 400
    assert "Não foi possível confirmar" in resposta.text


def test_token_de_empresa_desassociada_informa_o_motivo(client: TestClient):
    gestor = cabecalho(client, "gestor@demo.com")
    empresa = cabecalho(client, "empresa@demo.com")
    client.post(
        "/empresas/me/solicitar-desassociacao",
        json={"motivo": "Encerramos as atividades"},
        headers=empresa,
    )
    client.patch(
        "/empresas/empresa-demo/desassociacao", json={"aprovar": True}, headers=gestor
    )

    resposta = client.get("/registros/", headers=empresa)
    assert resposta.status_code == 403
    assert resposta.json()["detail"]["codigo"] == "CADASTRO_DESASSOCIADO"


def test_sincronizacao_valida_cada_item(client: TestClient):
    empresa = cabecalho(client, "empresa2@demo.com")
    lote = {
        "registros": [
            lancamento(client_id="lote-1"),
            lancamento(client_id="lote-2", volume_total=0),
            lancamento(client_id="lote-3", material_id="inexistente"),
        ]
    }
    resposta = client.post("/registros/sincronizar", json=lote, headers=empresa)
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["total_criados"] == 1
    assert dados["total_erros"] == 2
    assert [erro["client_id"] for erro in dados["erros"]] == ["lote-2", "lote-3"]


def test_cotacao_usada_na_estimativa(client: TestClient, monkeypatch):
    monkeypatch.setattr("src.routers.cotacao.obter_cotacao_dolar", lambda: 5.5)
    resposta = client.get("/cotacao/")
    assert resposta.status_code == 200
    assert resposta.json() == {
        "moeda": "BRL",
        "dolar": 5.5,
        "valor_tonelada_usd": 5.0,
        "valor_tonelada_brl": 27.5,
    }
