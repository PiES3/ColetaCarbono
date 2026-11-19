import pytest
from fastapi.testclient import TestClient

from src.services.email_service import email_service


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


def _solicitar(
    client: TestClient, registro_id: str, headers: dict[str, str], motivo: str
):
    return client.patch(
        f"/registros/{registro_id}/solicitar-correcao",
        json={"motivo_correcao": motivo},
        headers=headers,
    )


@pytest.fixture
def emails_enviados(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    enviados: list[dict[str, str]] = []

    def registrar(destinatario: str, assunto: str, corpo: str) -> bool:
        enviados.append({"para": destinatario, "assunto": assunto, "corpo": corpo})
        return True

    monkeypatch.setattr(email_service, "enviar", registrar)
    return enviados


def test_prefeitura_solicita_correcao_com_justificativa(
    client: TestClient, emails_enviados: list[dict[str, str]]
):
    """
    A prefeitura devolve o lançamento pendente para a empresa corrigir. Ele
    continua pendente, guarda a justificativa e a data do pedido, o pedido
    fica no histórico e a empresa é avisada por e-mail.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    registro = _lancar(client, empresa)

    resposta = _solicitar(
        client, registro["id"], gestor, "  O ticket da balança mostra 10 t.  "
    )
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["status_validacao"] == "PENDENTE"
    assert dados["correcao_solicitada"] is True
    assert dados["motivo_correcao"] == "O ticket da balança mostra 10 t."
    assert dados["data_solicitacao_correcao"]
    assert dados["validador_id"] is None

    visto_pela_empresa = client.get(
        f"/registros/{registro['id']}", headers=empresa
    ).json()
    assert visto_pela_empresa["correcao_solicitada"] is True
    assert visto_pela_empresa["motivo_correcao"] == "O ticket da balança mostra 10 t."

    alteracoes = client.get(
        "/registros/alteracoes",
        params={"registro_id": registro["id"]},
        headers=empresa,
    ).json()
    pedido = next(a for a in alteracoes if a["campo"] == "correcao_solicitada")
    assert pedido["valor_anterior"] is None
    assert pedido["valor_novo"] == "O ticket da balança mostra 10 t."
    assert pedido["autor_id"] == "gestor-demo"
    assert pedido["autor_nome"] == "Gestor Demo"

    assert len(emails_enviados) == 1
    assert emails_enviados[0]["para"] == "empresa@demo.com"
    assert "correção" in emails_enviados[0]["assunto"]
    assert "O ticket da balança mostra 10 t." in emails_enviados[0]["corpo"]
    assert "Quixadá" in emails_enviados[0]["corpo"]


def test_lancamento_em_correcao_nao_pode_ser_validado(client: TestClient):
    """
    Enquanto a empresa não corrige, o lançamento não pode ser validado nem
    receber um segundo pedido de correção. A recusa continua possível e
    encerra o pedido.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    registro = _lancar(client, empresa)
    assert (
        _solicitar(client, registro["id"], gestor, "Confira o percentual.")
    ).status_code == 200

    validacao = client.patch(
        f"/registros/{registro['id']}/validar",
        json={"volume_validado": 12.4},
        headers=gestor,
    )
    assert validacao.status_code == 400
    assert "correção" in validacao.json()["detail"]

    via_status = client.patch(
        f"/registros/{registro['id']}/status",
        json={"status_validacao": "VALIDADO"},
        headers=gestor,
    )
    assert via_status.status_code == 400

    de_novo = _solicitar(client, registro["id"], gestor, "Outro motivo qualquer.")
    assert de_novo.status_code == 400

    recusa = client.patch(
        f"/registros/{registro['id']}/rejeitar",
        json={"motivo_rejeicao": "A empresa não respondeu."},
        headers=gestor,
    )
    assert recusa.status_code == 200
    dados = recusa.json()
    assert dados["status_validacao"] == "REJEITADO"
    assert dados["correcao_solicitada"] is False
    assert dados["motivo_correcao"] is None
    assert dados["data_solicitacao_correcao"] is None


def test_correcao_da_empresa_devolve_o_lancamento_para_a_fila(client: TestClient):
    """
    Quando a empresa salva a correção, o pedido é encerrado, o lançamento
    volta para a fila e a prefeitura pode validá-lo. Salvar sem mudar nada
    mantém o pedido em aberto.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    registro = _lancar(client, empresa)
    url = f"/registros/{registro['id']}"
    _solicitar(client, registro["id"], gestor, "O ticket da balança mostra 10 t.")

    sem_mudanca = client.patch(url, json={"volume_total": 12.4}, headers=empresa)
    assert sem_mudanca.status_code == 200
    assert sem_mudanca.json()["correcao_solicitada"] is True

    corrigido = client.patch(url, json={"volume_total": 10.0}, headers=empresa)
    assert corrigido.status_code == 200
    dados = corrigido.json()
    assert dados["status_validacao"] == "PENDENTE"
    assert dados["correcao_solicitada"] is False
    assert dados["motivo_correcao"] is None
    assert dados["volume_total"] == 10.0

    alteracoes = client.get(
        "/registros/alteracoes", params={"registro_id": registro["id"]}, headers=empresa
    ).json()
    encerramento = next(
        a
        for a in alteracoes
        if a["campo"] == "correcao_solicitada" and a["valor_novo"] is None
    )
    assert encerramento["valor_anterior"] == "O ticket da balança mostra 10 t."
    assert encerramento["autor_nome"] == "Empresa Demo"

    validacao = client.patch(
        f"{url}/validar", json={"volume_validado": 10.0}, headers=gestor
    )
    assert validacao.status_code == 200
    assert validacao.json()["status_validacao"] == "VALIDADO"


def test_filtro_de_lancamentos_com_correcao_solicitada(client: TestClient):
    """
    A listagem separa os lançamentos que aguardam correção dos que estão na
    fila de validação, para a empresa e para a prefeitura.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    em_correcao = _lancar(client, empresa, volume_total=7.0)
    na_fila = _lancar(client, empresa, volume_total=8.0)
    _solicitar(client, em_correcao["id"], gestor, "Confira o material.")

    for headers in (empresa, gestor):
        aguardando = client.get(
            "/registros/",
            params={"status": "PENDENTE", "correcao_solicitada": True},
            headers=headers,
        )
        ids = [r["id"] for r in aguardando.json()]
        assert em_correcao["id"] in ids
        assert na_fila["id"] not in ids
        assert int(aguardando.headers["X-Total-Count"]) == len(ids)

        fila = client.get(
            "/registros/",
            params={"status": "PENDENTE", "correcao_solicitada": False},
            headers=headers,
        )
        ids = [r["id"] for r in fila.json()]
        assert na_fila["id"] in ids
        assert em_correcao["id"] not in ids


def test_regras_do_pedido_de_correcao(client: TestClient):
    """
    Só a prefeitura do município pede correção, só de lançamento pendente e
    sempre com uma justificativa de 5 a 500 caracteres.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    outra_cidade = _headers(client, "gestor2@demo.com")
    registro = _lancar(client, empresa)
    url = f"/registros/{registro['id']}/solicitar-correcao"
    motivo = {"motivo_correcao": "Confira a tonelagem."}

    assert client.patch(url, json=motivo).status_code == 401
    assert client.patch(url, json=motivo, headers=empresa).status_code == 403
    assert client.patch(url, json=motivo, headers=outra_cidade).status_code == 404
    assert (
        client.patch(
            "/registros/nao-existe/solicitar-correcao", json=motivo, headers=gestor
        ).status_code
        == 404
    )

    assert client.patch(url, json={}, headers=gestor).status_code == 400
    assert (
        client.patch(url, json={"motivo_correcao": "   "}, headers=gestor)
    ).status_code == 400
    assert (
        client.patch(url, json={"motivo_correcao": "abc"}, headers=gestor)
    ).status_code == 422
    assert (
        client.patch(url, json={"motivo_correcao": "x" * 501}, headers=gestor)
    ).status_code == 422
    pelo_alias = client.patch(
        url, json={"justificativa": "Confira o mês."}, headers=gestor
    )
    assert pelo_alias.status_code == 200
    assert pelo_alias.json()["motivo_correcao"] == "Confira o mês."

    validado = _lancar(client, empresa)
    client.patch(
        f"/registros/{validado['id']}/validar",
        json={"volume_validado": 12.4},
        headers=gestor,
    )
    resposta = client.patch(
        f"/registros/{validado['id']}/solicitar-correcao", json=motivo, headers=gestor
    )
    assert resposta.status_code == 400

    rejeitado = _lancar(client, empresa)
    client.patch(
        f"/registros/{rejeitado['id']}/rejeitar",
        json={"motivo_rejeicao": "Lançamento duplicado."},
        headers=gestor,
    )
    resposta = client.patch(
        f"/registros/{rejeitado['id']}/solicitar-correcao", json=motivo, headers=gestor
    )
    assert resposta.status_code == 400


def test_empresa_pode_excluir_lancamento_em_correcao(client: TestClient):
    """A empresa também pode desistir do lançamento e excluí-lo."""
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    registro = _lancar(client, empresa)
    _solicitar(client, registro["id"], gestor, "Lançamento parece duplicado.")

    resposta = client.delete(f"/registros/{registro['id']}", headers=empresa)
    assert resposta.status_code == 204
    consulta = client.get(f"/registros/{registro['id']}", headers=gestor)
    assert consulta.status_code == 404
