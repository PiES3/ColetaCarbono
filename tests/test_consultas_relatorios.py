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


def test_relatorio_registra_periodo_filtros_e_empresas(client: TestClient, monkeypatch):
    """
    O relatório traz no cabeçalho o período e os filtros aplicados, segmenta
    por empresa e deixa os rejeitados fora das somas. O PDF reflete os mesmos
    filtros e identifica o município.
    """
    monkeypatch.setattr(
        "src.services.services.obter_cotacao_dolar", lambda *_args, **_kw: 5.0
    )
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")
    for periodo, material, volume in (
        ("2026-03", "papel", 10.0),
        ("2026-04", "vidro", 20.0),
    ):
        resposta = client.post(
            "/registros/gestor",
            json={
                "empresa_id": "empresa-demo",
                "material_id": material,
                "periodo": periodo,
                "volume_total": volume,
                "percentual_reciclado": 50.0,
            },
            headers=gestor,
        )
        assert resposta.status_code == 201
    rejeitado = _lancar(
        client, empresa, material_id="vidro", periodo="2026-04", volume_total=999.0
    )
    client.patch(
        f"/registros/{rejeitado['id']}/rejeitar",
        json={"motivo_rejeicao": "Volume fora da realidade"},
        headers=gestor,
    )

    filtros = {
        "agrupamento": "mensal",
        "periodo_inicio": "2026-03",
        "periodo_fim": "2026-04",
        "empresa_id": "empresa-demo",
        "material_id": "vidro",
    }
    relatorio = client.get("/relatorios/", params=filtros, headers=gestor).json()
    assert relatorio["periodo_descricao"] == "03/2026 a 04/2026"
    assert relatorio["filtros_aplicados"] == [
        "Material: Vidro",
        "Empresa: Empresa Demo",
    ]
    assert relatorio["resumo"]["registros_rejeitados"] == 1
    assert relatorio["resumo"]["volume_total_declarado"] == 20.0
    assert relatorio["resumo"]["volume_total_validado"] == 20.0
    assert relatorio["resumo"]["percentual_medio_reciclado"] == 50.0
    assert [e["empresa_id"] for e in relatorio["por_empresa"]] == ["empresa-demo"]
    assert relatorio["por_empresa"][0]["carbono_evitado"] == 10.0

    geral = client.get(
        "/relatorios/", params={"agrupamento": "anual"}, headers=gestor
    ).json()
    assert geral["periodo_descricao"] == "Todo o histórico"
    assert geral["filtros_aplicados"] == []

    da_empresa = client.get(
        "/relatorios/", params={"agrupamento": "mensal"}, headers=empresa
    ).json()
    assert da_empresa["por_empresa"] == []

    pdf = client.get("/relatorios/exportar.pdf", params=filtros, headers=gestor)
    assert pdf.status_code == 200
    texto = _texto_do_pdf(pdf.content)
    for trecho in (
        "Município: Quixadá",
        "Período: 03/2026 a 04/2026",
        "Filtros: Material: Vidro; Empresa: Empresa Demo",
        "Emitido em:",
        "Consolidado por Empresa",
        "não tem validade jurídica",
    ):
        assert trecho.encode("cp1252") in texto


def test_serie_temporal_ignora_rejeitados(client: TestClient):
    """
    O gráfico dos últimos dias não conta lançamentos rejeitados, nem na
    quantidade nem no volume declarado.
    """
    empresa = _headers(client, "empresa@demo.com")
    gestor = _headers(client, "gestor@demo.com")

    def totais() -> tuple[int, float]:
        serie = client.get(
            "/dashboard/evolucao-temporal", params={"dias": 7}, headers=gestor
        ).json()["serie_diaria"]
        return (
            sum(dia["total_registros"] for dia in serie),
            sum(dia["volume_declarado"] for dia in serie),
        )

    antes = totais()
    registro = _lancar(client, empresa, volume_total=700.0)
    assert totais() == (antes[0] + 1, antes[1] + 700.0)

    client.patch(
        f"/registros/{registro['id']}/rejeitar",
        json={"motivo_rejeicao": "Volume fora da realidade"},
        headers=gestor,
    )
    assert totais() == antes
