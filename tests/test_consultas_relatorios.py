import re
import zlib

from fastapi.testclient import TestClient


def _headers(client: TestClient, email: str) -> dict[str, str]:
    resposta = client.post("/auth/login", json={"email": email, "senha": "demo123"})
    assert resposta.status_code == 200
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


def _lancar(client: TestClient, headers: dict[str, str], **campos) -> dict:
    corpo = {
        "material_id": "papel",
        "periodo": "2026-08",
        "volume_total": 5.0,
        "percentual_reciclado": 40.0,
        **campos,
    }
    resposta = client.post("/registros/", json=corpo, headers=headers)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _texto_do_pdf(conteudo: bytes) -> bytes:
    texto = b""
    for bloco in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", conteudo, re.S):
        try:
            texto += zlib.decompress(bloco)
        except zlib.error:
            texto += bloco
    return texto


def test_busca_combina_filtros_ordena_e_pagina(client: TestClient):
    """
    A busca da prefeitura combina material, período, empresa e status. A lista
    é ordenada pela data do lançamento, paginada e traz o total no cabeçalho.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    ids = [
        _lancar(client, empresa, material_id=material)["id"]
        for material in ("papel", "vidro", "papel")
    ]

    filtros = {
        "material_id": "papel",
        "empresa_id": "empresa-demo",
        "periodo": "2026-08",
        "status": "PENDENTE",
        "ordem": "asc",
        "limit": 1,
    }
    primeira = client.get("/registros/", params=filtros, headers=gestor)
    assert primeira.status_code == 200
    assert primeira.headers["x-total-count"] == "2"
    assert [r["id"] for r in primeira.json()] == [ids[0]]
    assert primeira.json()[0]["empresa_nome"] == "Empresa Demo"
    assert primeira.json()[0]["material_categoria"] == "Papel"

    segunda = client.get("/registros/", params={**filtros, "skip": 1}, headers=gestor)
    assert [r["id"] for r in segunda.json()] == [ids[2]]

    recentes = client.get(
        "/registros/", params={"material_id": "papel"}, headers=empresa
    ).json()
    assert [r["id"] for r in recentes[:2]] == [ids[2], ids[0]]

    validados = client.get(
        "/registros/", params={**filtros, "status": "VALIDADO"}, headers=gestor
    )
    assert validados.json() == []
    assert validados.headers["x-total-count"] == "0"

    outra_cidade = _headers(client, "gestor2@demo.com")
    de_fora = client.get(
        "/registros/", params={"material_id": "papel"}, headers=outra_cidade
    )
    assert de_fora.headers["x-total-count"] == "0"
