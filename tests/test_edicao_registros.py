from fastapi.testclient import TestClient


def _headers(client: TestClient, email: str) -> dict[str, str]:
    resposta = client.post("/auth/login", json={"email": email, "senha": "demo123"})
    assert resposta.status_code == 200
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


def _lancar(client: TestClient, headers: dict[str, str], **campos) -> dict:
    corpo = {
        "material_id": "papel",
        "periodo": "2026-09",
        "volume_total": 12.4,
        "percentual_reciclado": 35.0,
        **campos,
    }
    resposta = client.post("/registros/", json=corpo, headers=headers)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_empresa_corrige_lancamento_pendente_com_historico(client: TestClient):
    """
    A empresa corrige um lançamento pendente, e cada campo que mudou fica no
    histórico com autor e data/hora. Campos iguais não geram registro.
    """
    empresa = _headers(client, "empresa@demo.com")
    registro = _lancar(client, empresa)

    resposta = client.patch(
        f"/registros/{registro['id']}",
        json={
            "material_id": "plastico",
            "volume_total": 10.0,
            "percentual_reciclado": 35,
        },
        headers=empresa,
    )
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["material_id"] == "plastico"
    assert dados["material_categoria"] == "Plástico"
    assert dados["volume_total"] == 10.0
    assert dados["status_validacao"] == "PENDENTE"

    alteracoes = client.get(
        "/registros/alteracoes",
        params={"registro_id": registro["id"]},
        headers=empresa,
    ).json()
    assert {a["campo"] for a in alteracoes} == {"material", "volume_total"}
    material = next(a for a in alteracoes if a["campo"] == "material")
    assert material["acao"] == "EDICAO"
    assert material["valor_anterior"] == "Papel"
    assert material["valor_novo"] == "Plástico"
    assert material["autor_id"] == "empresa-demo"
    assert material["autor_nome"] == "Empresa Demo"
    assert material["created_at"]
    volume = next(a for a in alteracoes if a["campo"] == "volume_total")
    assert (volume["valor_anterior"], volume["valor_novo"]) == ("12.4", "10")


def test_lancamento_rejeitado_corrigido_volta_para_validacao(client: TestClient):
    """
    Corrigido pela empresa, o lançamento rejeitado perde o motivo da rejeição
    e volta para a fila de validação da prefeitura.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    registro = _lancar(client, empresa, volume_total=500.0)
    rejeicao = client.patch(
        f"/registros/{registro['id']}/rejeitar",
        json={"motivo_rejeicao": "Volume acima da capacidade"},
        headers=gestor,
    )
    assert rejeicao.status_code == 200

    resposta = client.patch(
        f"/registros/{registro['id']}", json={"volume_total": 50.0}, headers=empresa
    )
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["status_validacao"] == "PENDENTE"
    assert dados["motivo_rejeicao"] is None
    assert dados["validador_id"] is None

    fila = client.get("/registros/", params={"status": "PENDENTE"}, headers=gestor)
    assert registro["id"] in [r["id"] for r in fila.json()]

    alteracoes = client.get(
        "/registros/alteracoes",
        params={"registro_id": registro["id"]},
        headers=empresa,
    ).json()
    status_alterado = next(a for a in alteracoes if a["campo"] == "status_validacao")
    assert status_alterado["valor_anterior"] == "REJEITADO"
    assert status_alterado["valor_novo"] == "PENDENTE"


def test_lancamento_validado_fica_bloqueado(client: TestClient):
    """
    Depois de validado, o lançamento não pode ser editado nem excluído pela
    empresa, inclusive os lançados pela prefeitura.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    registro = _lancar(client, empresa)
    client.patch(
        f"/registros/{registro['id']}/validar",
        json={"volume_validado": 12.4},
        headers=gestor,
    )
    lancado_pela_prefeitura = client.post(
        "/registros/gestor",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "metal",
            "periodo": "2026-09",
            "volume_total": 2.0,
            "percentual_reciclado": 80.0,
        },
        headers=gestor,
    ).json()

    for registro_id in (registro["id"], lancado_pela_prefeitura["id"]):
        edicao = client.patch(
            f"/registros/{registro_id}", json={"volume_total": 1.0}, headers=empresa
        )
        assert edicao.status_code == 400
        exclusao = client.delete(f"/registros/{registro_id}", headers=empresa)
        assert exclusao.status_code == 400

    dados = client.get(f"/registros/{registro['id']}", headers=empresa).json()
    assert dados["volume_total"] == 12.4
    assert dados["status_validacao"] == "VALIDADO"


def test_empresa_exclui_lancamento_com_historico(client: TestClient):
    """
    A exclusão remove o lançamento e deixa no histórico um resumo dele, com
    autor e data/hora, visível para a empresa e para a prefeitura do município.
    """
    empresa = _headers(client, "empresa@demo.com")
    registro = _lancar(
        client, empresa, material_id="vidro", volume_total=3.5, percentual_reciclado=20
    )

    resposta = client.delete(f"/registros/{registro['id']}", headers=empresa)
    assert resposta.status_code == 204
    consulta = client.get(f"/registros/{registro['id']}", headers=empresa)
    assert consulta.status_code == 404

    alteracoes = client.get("/registros/alteracoes", headers=empresa).json()
    exclusao = next(a for a in alteracoes if a["registro_id"] == registro["id"])
    assert exclusao["acao"] == "EXCLUSAO"
    assert exclusao["valor_anterior"] == "Vidro · 2026-09 · 3.5 t · 20 %"
    assert exclusao["valor_novo"] is None
    assert exclusao["autor_nome"] == "Empresa Demo"

    gestor = _headers(client, "gestor@demo.com")
    do_municipio = client.get("/registros/alteracoes", headers=gestor).json()
    assert registro["id"] in [a["registro_id"] for a in do_municipio]

    outra_cidade = _headers(client, "gestor2@demo.com")
    de_fora = client.get("/registros/alteracoes", headers=outra_cidade).json()
    assert registro["id"] not in [a["registro_id"] for a in de_fora]


def test_edicao_restrita_a_empresa_dona_do_lancamento(client: TestClient):
    """
    Só a empresa dona do lançamento edita ou exclui. Outra empresa recebe 404,
    a prefeitura recebe 403 e os campos seguem as mesmas regras do cadastro.
    """
    empresa = _headers(client, "empresa@demo.com")
    outra_empresa = _headers(client, "empresa2@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    registro = _lancar(client, empresa)
    url = f"/registros/{registro['id']}"

    assert client.patch(url, json={"volume_total": 1.0}).status_code == 401
    assert (
        client.patch(url, json={"volume_total": 1.0}, headers=outra_empresa)
    ).status_code == 404
    assert client.delete(url, headers=outra_empresa).status_code == 404
    assert (
        client.patch(url, json={"volume_total": 1.0}, headers=gestor)
    ).status_code == 403
    assert client.delete(url, headers=gestor).status_code == 403

    for campos in (
        {"volume_total": 0},
        {"percentual_reciclado": 120},
        {"periodo": "2999-01"},
    ):
        assert client.patch(url, json=campos, headers=empresa).status_code == 422

    material_invalido = client.patch(
        url, json={"material_id": "inexistente"}, headers=empresa
    )
    assert material_invalido.status_code == 400

    assert client.get(url, headers=empresa).json()["volume_total"] == 12.4
