from fastapi.testclient import TestClient

from src.app import app
from src.core.database import get_db
from src.models.models import Empresa
from src.schemas.validacao import digito_verificador_cnpj
from tests.conftest import TestingSessionLocal


def _gerar_cnpj(base12: str) -> str:
    d1 = digito_verificador_cnpj(base12)
    d2 = digito_verificador_cnpj(base12 + d1)
    return base12 + d1 + d2


def _headers_login(
    client: TestClient, email: str, senha: str = "demo123"
) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": email, "senha": senha})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _criar_empresa_aprovada(
    client: TestClient, base12: str, email: str
) -> tuple[str, dict[str, str]]:
    cnpj = _gerar_cnpj(base12)
    senha = "SenhaForte@123"
    resp = client.post(
        "/auth/register",
        json={
            "cnpj": cnpj,
            "email": email,
            "senha": senha,
            "razao_social": f"Empresa {base12} LTDA",
            "prefeitura_id": "prefeitura-quixada",
        },
    )
    assert resp.status_code == 201, resp.text
    empresa_id = resp.json()["id"]

    db = TestingSessionLocal()
    emp = db.get(Empresa, empresa_id)
    assert emp is not None and emp.token_confirmacao_email
    token_conf = emp.token_confirmacao_email
    db.close()

    assert (
        client.get("/auth/confirm-email", params={"token": token_conf}).status_code
        == 200
    )

    gestor = _headers_login(client, "gestor@demo.com")
    assert (
        client.patch(
            f"/empresas/{empresa_id}/status",
            json={"novo_status": "APROVADA"},
            headers=gestor,
        ).status_code
        == 200
    )

    return empresa_id, _headers_login(client, email, senha)


# ============================================================================
# [RF#004] Exclusão / Desassociação de Empresa mediante validação da prefeitura
# ============================================================================


def test_rf004_fluxo_completo_desassociacao_empresa(client: TestClient):
    empresa_id, headers_emp = _criar_empresa_aprovada(
        client, "414243440001", "desassociar@empresa.com"
    )
    headers_gestor = _headers_login(client, "gestor@demo.com")
    headers_outro_gestor = _headers_login(client, "gestor2@demo.com")

    # 1. Empresa solicita desassociação e depois cancela
    resp_sol = client.post(
        "/empresas/me/solicitar-desassociacao",
        json={"motivo": "Encerramento temporário"},
        headers=headers_emp,
    )
    assert resp_sol.status_code == 200
    assert resp_sol.json()["desassociacao_solicitada"] is True
    assert resp_sol.json()["motivo_desassociacao"] == "Encerramento temporário"
    assert resp_sol.json()["empresa_status"] == "APROVADA"

    # Solicitação duplicada deve retornar 400
    assert (
        client.post(
            "/empresas/me/solicitar-desassociacao",
            json={"motivo": "Duplicada"},
            headers=headers_emp,
        ).status_code
        == 400
    )

    # Cancelamento pela própria empresa
    resp_cancel = client.delete(
        "/empresas/me/solicitar-desassociacao", headers=headers_emp
    )
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["desassociacao_solicitada"] is False

    # 2. Solicita novamente e prefeitura recusa em um primeiro momento
    assert (
        client.post(
            "/empresas/me/solicitar-desassociacao",
            json={"motivo": "Mudança de município"},
            headers=headers_emp,
        ).status_code
        == 200
    )

    # Gestor do próprio município enxerga na fila; gestor de outro município não
    fila_quixada = client.get(
        "/empresas/solicitacoes-desassociacao", headers=headers_gestor
    ).json()
    assert any(e["id"] == empresa_id for e in fila_quixada)

    fila_outro = client.get(
        "/empresas/solicitacoes-desassociacao", headers=headers_outro_gestor
    ).json()
    assert all(e["id"] != empresa_id for e in fila_outro)

    # Gestor de outro município não consegue decidir (404)
    assert (
        client.patch(
            f"/empresas/{empresa_id}/desassociacao",
            json={"aprovar": True},
            headers=headers_outro_gestor,
        ).status_code
        == 404
    )

    # Gestor recusa a desassociação -> empresa permanece APROVADA
    resp_recusa = client.patch(
        f"/empresas/{empresa_id}/desassociacao",
        json={"aprovar": False, "motivo_resposta": "Pendência de lote em análise"},
        headers=headers_gestor,
    )
    assert resp_recusa.status_code == 200
    assert resp_recusa.json()["empresa_status"] == "APROVADA"
    assert resp_recusa.json()["desassociacao_solicitada"] is False

    # 3. Nova solicitação aprovada pelo gestor -> DESASSOCIADA e bloqueio de acesso
    assert (
        client.post(
            "/empresas/me/solicitar-desassociacao",
            json={"motivo": "Encerramento definitivo das atividades"},
            headers=headers_emp,
        ).status_code
        == 200
    )
    resp_aprov = client.patch(
        f"/empresas/{empresa_id}/desassociacao",
        json={"aprovar": True},
        headers=headers_gestor,
    )
    assert resp_aprov.status_code == 200
    assert resp_aprov.json()["empresa_status"] == "DESASSOCIADA"
    assert resp_aprov.json()["desassociacao_solicitada"] is False

    # Token anterior da empresa não pode mais acessar rotas de empresa aprovada
    assert client.get("/empresas/me", headers=headers_emp).status_code == 403

    # Novo login informa CADASTRO_DESASSOCIADO
    resp_login = client.post(
        "/auth/login",
        json={"email": "desassociar@empresa.com", "senha": "SenhaForte@123"},
    )
    assert resp_login.status_code == 403
    assert resp_login.json()["detail"]["codigo"] == "CADASTRO_DESASSOCIADO"


# ============================================================================
# [RNF#001] Offline-First: Sincronização em lote com idempotência + [RNF#002]
# ============================================================================


def test_rnf001_sincronizacao_offline_lote_idempotente_e_conama(client: TestClient):
    headers_emp = _headers_login(client, "empresa@demo.com")

    # Verifica cores CONAMA 275 nos materiais (RNF#002)
    materiais = client.get("/materiais/", headers=headers_emp).json()
    cores = {m["id"]: m["cor_conama"] for m in materiais}
    assert cores["papel"] == "#0057B8"
    assert cores["plastico"] == "#D62828"
    assert cores["vidro"] == "#2A9D49"
    assert cores["metal"] == "#F4B400"

    lote = {
        "registros": [
            {
                "client_id": "offline-uuid-001",
                "material_id": "papel",
                "periodo": "2026-09",
                "volume_total": 12.5,
                "percentual_reciclado": 80.0,
            },
            {
                "client_id": "offline-uuid-002",
                "material_id": "plastico",
                "periodo": "2026-10",
                "volume_total": 25.0,
                "percentual_reciclado": 60.0,
            },
            {
                "client_id": "offline-uuid-invalido",
                "material_id": "material-inexistente",
                "periodo": "2026-10",
                "volume_total": 5.0,
                "percentual_reciclado": 50.0,
            },
        ]
    }

    resp1 = client.post("/registros/sincronizar", json=lote, headers=headers_emp)
    assert resp1.status_code == 200
    dados1 = resp1.json()
    assert dados1["total_recebidos"] == 3
    assert dados1["total_criados"] == 2
    assert dados1["total_duplicados"] == 0
    assert dados1["total_erros"] == 1
    ids_primeira_vez = [r["id"] for r in dados1["registros"]]

    # Reenvio do mesmo lote (queda de conexão no app mobile) -> não duplica!
    resp2 = client.post(
        "/registros/lote",
        json={"registros": lote["registros"][:2]},
        headers=headers_emp,
    )
    assert resp2.status_code == 200
    dados2 = resp2.json()
    assert dados2["total_criados"] == 0
    assert dados2["total_duplicados"] == 2
    assert [r["id"] for r in dados2["registros"]] == ids_primeira_vez


# ============================================================================
# [RF#013], [RF#014] e [RF#015] Relatórios, PDF e Gráficos Temporais (28 dias)
# ============================================================================


def test_rf013_rf014_rf015_relatorios_pdf_e_evolucao_28_dias(
    client: TestClient, monkeypatch
):
    monkeypatch.setattr(
        "src.services.services.obter_cotacao_dolar", lambda *_args, **_kw: 5.0
    )

    headers_gestor = _headers_login(client, "gestor@demo.com")
    headers_emp = _headers_login(client, "empresa@demo.com")

    # Cria registros validados em meses distintos para alimentar relatórios e gráficos
    for periodo, mat, vol in (
        ("2025-12", "vidro", 30.0),
        ("2026-09", "papel", 40.0),
        ("2026-10", "metal", 60.0),
    ):
        r = client.post(
            "/registros/gestor",
            json={
                "empresa_id": "empresa-demo",
                "material_id": mat,
                "periodo": periodo,
                "volume_total": vol,
                "percentual_reciclado": 100.0,
            },
            headers=headers_gestor,
        )
        assert r.status_code == 201

    # [RF#013] Agrupamentos semanal, mensal e anual + filtro por material
    for agrup in ("semanal", "mensal", "anual"):
        resp_rel = client.get(
            f"/relatorios/?agrupamento={agrup}", headers=headers_gestor
        )
        assert resp_rel.status_code == 200
        rel = resp_rel.json()
        assert rel["agrupamento"] == agrup
        assert rel["escopo"] == "PREFEITURA"
        assert rel["resumo"]["registros_validados"] >= 3
        assert len(rel["grupos"]) >= 1
        assert len(rel["por_material"]) >= 3
        assert all(len(g["por_material"]) >= 1 for g in rel["grupos"])

    # Segmentado por tipo de material (apenas papel) na visão da Empresa
    resp_mat = client.get(
        "/relatorios/?agrupamento=mensal&material_id=papel", headers=headers_emp
    )
    assert resp_mat.status_code == 200
    rel_mat = resp_mat.json()
    assert rel_mat["escopo"] == "EMPRESA"
    assert [m["material_id"] for m in rel_mat["por_material"]] == ["papel"]

    # [RF#014] Exportação de Relatório em PDF (Prefeitura e Empresa)
    for rota in (
        "/relatorios/exportar.pdf?agrupamento=mensal",
        "/dashboard/relatorio.pdf?agrupamento=anual",
    ):
        resp_pdf = client.get(rota, headers=headers_gestor)
        assert resp_pdf.status_code == 200
        assert resp_pdf.headers["content-type"] == "application/pdf"
        assert "attachment;" in resp_pdf.headers["content-disposition"]
        assert resp_pdf.content.startswith(b"%PDF-1.")
        assert len(resp_pdf.content) > 800

    resp_pdf_emp = client.get(
        "/relatorios/exportar.pdf?agrupamento=semanal", headers=headers_emp
    )
    assert resp_pdf_emp.status_code == 200
    assert resp_pdf_emp.content.startswith(b"%PDF-1.")

    # [RF#015] Painel visual e gráficos temporais (evolução nos últimos 28 dias)
    resp_evo = client.get(
        "/dashboard/evolucao-temporal?dias=28", headers=headers_gestor
    )
    assert resp_evo.status_code == 200
    evo = resp_evo.json()
    assert evo["dias"] == 28
    assert len(evo["serie_diaria"]) == 28
    datas = [item["data"] for item in evo["serie_diaria"]]
    assert datas == sorted(datas)
    assert evo["volume_periodo_atual"] > 0
    assert evo["carbono_periodo_atual"] > 0

    resp_evo_emp = client.get(
        "/registros/estatisticas/evolucao-diaria?dias=14", headers=headers_emp
    )
    assert resp_evo_emp.status_code == 200
    assert len(resp_evo_emp.json()["serie_diaria"]) == 14


# ============================================================================
# Endpoints de Estado de Saúde (Health Check: Liveness & Readiness)
# ============================================================================


def test_endpoints_saude_live_ready_e_degradacao(client: TestClient):
    # 1. Liveness (GET, HEAD e alias /healthz)
    for rota in ("/health/live", "/healthz"):
        resp_live = client.get(rota)
        assert resp_live.status_code == 200
        corpo_live = resp_live.json()
        assert corpo_live["status"] == "ok"
        assert corpo_live["servico"] == "ColetaCarbono"
        assert corpo_live["uptime_segundos"] >= 0

    assert client.head("/health/live").status_code == 200
    assert client.head("/health").status_code == 200

    # 2. Saúde geral e Readiness com banco saudável
    for rota in ("/health", "/health/", "/health/ready", "/readyz"):
        resp_ready = client.get(rota)
        assert resp_ready.status_code == 200
        corpo = resp_ready.json()
        assert corpo["status"] == "ok"
        assert corpo["pronto"] is True
        assert corpo["banco_dados"]["status"] == "ok"
        assert corpo["banco_dados"]["dialeto"] == "sqlite"
        assert corpo["banco_dados"]["conectado"] is True
        assert corpo["banco_dados"]["schema_integro"] is True
        assert corpo["banco_dados"]["latencia_ms"] >= 0

    # 3. Falha simulada de banco de dados deve retornar HTTP 503 em /health e /ready
    class _SessaoComFalha:
        def get_bind(self):
            return None

        def execute(self, *_args, **_kwargs):
            raise RuntimeError("Banco indisponível")

    override_anterior = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: _SessaoComFalha()
    try:
        resp_falha = client.get("/health/ready")
        assert resp_falha.status_code == 503
        corpo_falha = resp_falha.json()
        assert corpo_falha["status"] == "error"
        assert corpo_falha["pronto"] is False
        assert corpo_falha["banco_dados"]["conectado"] is False
        assert "Banco indisponível" in corpo_falha["banco_dados"]["detalhe"]

        # Mesmo com o banco fora, o liveness continua respondendo 200 OK
        assert client.get("/health/live").status_code == 200
    finally:
        if override_anterior is not None:
            app.dependency_overrides[get_db] = override_anterior
        else:
            app.dependency_overrides.pop(get_db, None)
