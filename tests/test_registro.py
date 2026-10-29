from fastapi.testclient import TestClient

from src.models.models import Empresa, Prefeitura
from src.schemas.enums import StatusVinculo
from tests.conftest import TestingSessionLocal


def _obter_token_gestor(client: TestClient) -> str:
    login_resp = client.post(
        "/auth/login",
        json={"email": "gestor@demo.com", "senha": "demo123"},
    )
    assert login_resp.status_code == 200
    return login_resp.json()["access_token"]


def _obter_token_empresa(client: TestClient) -> str:
    login_resp = client.post(
        "/auth/login",
        json={"email": "empresa@demo.com", "senha": "demo123"},
    )
    assert login_resp.status_code == 200
    return login_resp.json()["access_token"]


# ============================================================================
# Testes do Lançamento de Resíduos pelo Gestor da Prefeitura
# ============================================================================


def test_gestor_cria_registro_sucesso(client: TestClient):
    """
    Testa o fluxo em que o gestor da prefeitura lança um registro de resíduos
    em nome de uma empresa vinculada à sua prefeitura.
    O registro deve nascer com status VALIDADO, registrando o gestor como
    autor e validador, e calculando carbono evitado e estimativa financeira.
    """
    token_gestor = _obter_token_gestor(client)

    payload = {
        "empresa_id": "empresa-demo",
        "material_id": "papel",
        "periodo": "2026-10",
        "volume_total": 100.0,
        "percentual_reciclado": 50.0,
    }

    response = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    assert response.status_code == 201
    dados = response.json()

    assert dados["empresa_id"] == "empresa-demo"
    assert dados["material_id"] == "papel"
    assert dados["periodo"] == "2026-10"
    assert dados["volume_total"] == 100.0
    assert dados["percentual_reciclado"] == 50.0
    assert dados["volume_validado"] == 100.0
    assert dados["status_validacao"] == "VALIDADO"
    assert dados["criado_por_gestor_id"] == "gestor-demo"
    assert dados["validador_id"] == "gestor-demo"
    assert dados["carbonoevitado"] == 50.0  # 100 * (50/100) * 1.0 (ipcc do papel)
    assert dados["valorestimado"] is not None
    assert dados["valorestimado"] > 0
    assert dados["inserido_pela_prefeitura"] is True
    assert dados["origem"] == "PREFEITURA"
    assert dados["nome_gestor"] == "Gestor Demo"


def test_gestor_cria_registro_com_volume_validado_customizado(client: TestClient):
    """
    Testa quando o gestor informa explicitamente o volume_validado diferente
    do volume_total_original.
    """
    token_gestor = _obter_token_gestor(client)

    payload = {
        "empresa_id": "empresa-demo",
        "material_id": "plastico",
        "periodo": "2026-10",
        "volume_total": 200.0,
        "volume_validado": 180.0,
        "percentual_reciclado": 100.0,
    }

    response = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    assert response.status_code == 201
    dados = response.json()
    assert dados["volume_total"] == 200.0
    assert dados["volume_validado"] == 180.0
    # 180 * (100/100) * 1.0 = 180.0
    assert dados["carbonoevitado"] == 180.0
    assert dados["status_validacao"] == "VALIDADO"
    assert dados["inserido_pela_prefeitura"] is True


def test_empresa_visualiza_lancamento_no_historico(client: TestClient):
    """
    A empresa vinculada visualiza no seu histórico o lançamento efetuado
    pela prefeitura, com indicação explícita de que foi inserido pela prefeitura.
    """
    token_gestor = _obter_token_gestor(client)
    client.post(
        "/registros/gestor",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-10",
            "volume_total": 100.0,
            "percentual_reciclado": 50.0,
        },
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    token_empresa = _obter_token_empresa(client)

    response = client.get(
        "/registros/?empresa_id=empresa-demo",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )

    assert response.status_code == 200
    registros = response.json()
    assert len(registros) > 0

    # Localiza o registro lançado pela prefeitura
    registro_prefeitura = next(
        (r for r in registros if r["inserido_pela_prefeitura"] is True), None
    )
    assert registro_prefeitura is not None
    assert registro_prefeitura["origem"] == "PREFEITURA"
    assert registro_prefeitura["criado_por_gestor_id"] == "gestor-demo"
    assert registro_prefeitura["validador_id"] == "gestor-demo"
    assert registro_prefeitura["nome_gestor"] == "Gestor Demo"
    assert registro_prefeitura["status_validacao"] == "VALIDADO"


def test_empresa_cria_registro_normal_pendente(client: TestClient):
    """
    Garante que registros inseridos sem intervenção do gestor nascem
    com status PENDENTE e inserido_pela_prefeitura=False.
    """
    payload = {
        "empresa_id": "empresa-demo",
        "material_id": "vidro",
        "periodo": "2026-10",
        "volume_total": 50.0,
        "percentual_reciclado": 80.0,
    }

    response = client.post("/registros/", json=payload)
    assert response.status_code == 201
    dados = response.json()

    assert dados["status_validacao"] == "PENDENTE"
    assert dados["criado_por_gestor_id"] is None
    assert dados["validador_id"] is None
    assert dados["inserido_pela_prefeitura"] is False
    assert dados["origem"] == "EMPRESA"
    assert dados["nome_gestor"] is None


def test_filtro_historico_apenas_prefeitura(client: TestClient):
    """
    Verifica a capacidade de filtrar no histórico apenas os registros
    inseridos pela prefeitura ou apenas os enviados pela empresa.
    """
    token_gestor = _obter_token_gestor(client)
    client.post(
        "/registros/gestor",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "metal",
            "periodo": "2026-10",
            "volume_total": 40.0,
            "percentual_reciclado": 100.0,
        },
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "plastico",
            "periodo": "2026-10",
            "volume_total": 60.0,
            "percentual_reciclado": 100.0,
        },
    )

    token_empresa = _obter_token_empresa(client)

    # Filtrar apenas prefeitura
    resp_pref = client.get(
        "/registros/?empresa_id=empresa-demo&apenas_prefeitura=true",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_pref.status_code == 200
    dados_pref = resp_pref.json()
    assert len(dados_pref) > 0
    for reg in dados_pref:
        assert reg["inserido_pela_prefeitura"] is True
        assert reg["origem"] == "PREFEITURA"

    # Filtrar apenas empresa
    resp_emp = client.get(
        "/registros/?empresa_id=empresa-demo&apenas_prefeitura=false",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_emp.status_code == 200
    dados_emp = resp_emp.json()
    assert len(dados_emp) > 0
    for reg in dados_emp:
        assert reg["inserido_pela_prefeitura"] is False
        assert reg["origem"] == "EMPRESA"


def test_gestor_nao_pode_lancar_para_empresa_de_outra_prefeitura(client: TestClient):
    """
    O gestor só pode lançar registros para empresas vinculadas à sua própria prefeitura.
    Se a empresa pertencer a outra prefeitura, a requisição deve ser rejeitada com 400.
    """
    # Cria prefeitura B e empresa vinculada a B
    db = TestingSessionLocal()
    pref_b = Prefeitura(id="prefeitura-outra", nome="Outra Cidade")
    empresa_b = Empresa(
        id="empresa-outra",
        prefeitura_id="prefeitura-outra",
        cnpj="99999999000199",
        razao_social="Outra Empresa LTDA",
        email="outra@empresa.com",
        pwd_hash="hashed_123",
        empresa_status=StatusVinculo.APROVADA,
    )
    db.add(pref_b)
    db.add(empresa_b)
    db.commit()
    db.close()

    token_gestor = _obter_token_gestor(client)  # Gestor de 'prefeitura-quixada'

    payload = {
        "empresa_id": "empresa-outra",
        "material_id": "papel",
        "periodo": "2026-10",
        "volume_total": 100.0,
        "percentual_reciclado": 50.0,
    }

    response = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "A empresa selecionada não está vinculada à sua prefeitura."
    )


def test_gestor_nao_pode_lancar_para_empresa_nao_aprovada(client: TestClient):
    """
    Se a empresa pertencer à prefeitura mas ainda não tiver o vínculo aprovado
    (por exemplo, AGUARDANDO_VALIDACAO ou RECUSADA), o lançamento deve ser recusado.
    """
    db = TestingSessionLocal()
    empresa_pendente = Empresa(
        id="empresa-pendente-quixada",
        prefeitura_id="prefeitura-quixada",
        cnpj="88888888000188",
        razao_social="Empresa Pendente LTDA",
        email="pendente@empresa.com",
        pwd_hash="hashed_123",
        empresa_status=StatusVinculo.AGUARDANDO_VALIDACAO,
    )
    db.add(empresa_pendente)
    db.commit()
    db.close()

    token_gestor = _obter_token_gestor(client)

    payload = {
        "empresa_id": "empresa-pendente-quixada",
        "material_id": "papel",
        "periodo": "2026-10",
        "volume_total": 100.0,
        "percentual_reciclado": 50.0,
    }

    response = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "A empresa selecionada não possui vínculo aprovado com a prefeitura."
    )


def test_gestor_cria_registro_empresa_inexistente(client: TestClient):
    token_gestor = _obter_token_gestor(client)

    payload = {
        "empresa_id": "empresa-fantasma-999",
        "material_id": "papel",
        "periodo": "2026-10",
        "volume_total": 100.0,
        "percentual_reciclado": 50.0,
    }

    response = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Empresa não encontrada."


def test_gestor_cria_registro_material_inexistente(client: TestClient):
    token_gestor = _obter_token_gestor(client)

    payload = {
        "empresa_id": "empresa-demo",
        "material_id": "uranio-enriquecido",
        "periodo": "2026-10",
        "volume_total": 100.0,
        "percentual_reciclado": 50.0,
    }

    response = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Material não encontrado."


def test_empresa_proibida_de_chamar_endpoint_gestor(client: TestClient):
    """
    Empresas comuns não podem invocar /registros/gestor diretamente (403 Forbidden).
    """
    token_empresa = _obter_token_empresa(client)

    payload = {
        "empresa_id": "empresa-demo",
        "material_id": "papel",
        "periodo": "2026-10",
        "volume_total": 100.0,
        "percentual_reciclado": 50.0,
    }

    response = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_empresa}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Acesso restrito à Prefeitura (Superusuário)."


def test_gestor_lista_empresas_vinculadas_para_selecao(client: TestClient):
    """
    Testa os endpoints que o gestor utiliza para listar e selecionar as
    empresas vinculadas à sua prefeitura.
    """
    token_gestor = _obter_token_gestor(client)

    # 1. Endpoint dedicado /empresas/vinculadas
    resp_vinculadas = client.get(
        "/empresas/vinculadas",
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_vinculadas.status_code == 200
    empresas = resp_vinculadas.json()
    assert len(empresas) >= 1
    assert any(e["id"] == "empresa-demo" for e in empresas)
    # Garante que não traz empresa de outra prefeitura
    assert all(e["prefeitura_id"] == "prefeitura-quixada" for e in empresas)

    # 2. Endpoint geral /empresas/ com token de gestor filtra automaticamente
    resp_geral = client.get(
        "/empresas/",
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_geral.status_code == 200
    empresas_geral = resp_geral.json()
    assert all(e["prefeitura_id"] == "prefeitura-quixada" for e in empresas_geral)


def test_obter_registro_detalhado_por_id(client: TestClient):
    """
    Testa a recuperação de um registro individual por ID.
    """
    token_gestor = _obter_token_gestor(client)

    payload = {
        "empresa_id": "empresa-demo",
        "material_id": "metal",
        "periodo": "2026-11",
        "volume_total": 75.0,
        "percentual_reciclado": 100.0,
    }

    criacao = client.post(
        "/registros/gestor",
        json=payload,
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    registro_id = criacao.json()["id"]

    response = client.get(f"/registros/{registro_id}")
    assert response.status_code == 200
    dados = response.json()
    assert dados["id"] == registro_id
    assert dados["inserido_pela_prefeitura"] is True
    assert dados["origem"] == "PREFEITURA"
    assert dados["nome_gestor"] == "Gestor Demo"


# ============================================================================
# Testes de Validação Total / Parcial e Rejeição de Registros pelo Gestor
# ============================================================================


def test_gestor_valida_registro_volume_total(client: TestClient):
    """
    Testa a validação de um registro pendente pelo gestor utilizando o volume
    total informado pela empresa.
    """
    # 1. Empresa cria um registro pendente
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-10",
            "volume_total": 120.0,
            "percentual_reciclado": 50.0,
        },
    )
    assert resp_criacao.status_code == 201
    registro_id = resp_criacao.json()["id"]

    token_gestor = _obter_token_gestor(client)

    # 2. Gestor valida o volume total sem passar volume_validado explícito
    resp_validacao = client.patch(
        f"/registros/{registro_id}/validar",
        json={},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_validacao.status_code == 200
    dados = resp_validacao.json()
    assert dados["status_validacao"] == "VALIDADO"
    assert dados["volume_validado"] == 120.0
    assert dados["carbonoevitado"] == 60.0  # 120.0 * 0.5 * 1.0
    assert dados["validador_id"] == "gestor-demo"
    assert dados["motivo_rejeicao"] is None


def test_gestor_valida_registro_parcialmente(client: TestClient):
    """
    Testa a validação parcial de um registro: empresa declara 100 kg,
    mas o gestor valida apenas 70 kg após a pesagem oficial.
    """
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "vidro",
            "periodo": "2026-10",
            "volume_total": 100.0,
            "percentual_reciclado": 100.0,
        },
    )
    assert resp_criacao.status_code == 201
    registro_id = resp_criacao.json()["id"]

    token_gestor = _obter_token_gestor(client)

    resp_validacao = client.patch(
        f"/registros/{registro_id}/validar",
        json={"volume_validado": 70.0},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_validacao.status_code == 200
    dados = resp_validacao.json()
    assert dados["status_validacao"] == "VALIDADO"
    assert dados["volume_total"] == 100.0
    assert dados["volume_validado"] == 70.0
    assert dados["carbonoevitado"] == 70.0  # 70 * 1.0 * 1.0
    assert dados["validador_id"] == "gestor-demo"


def test_gestor_rejeita_registro_com_motivo_sucesso(client: TestClient):
    """
    Testa o fluxo em que o gestor rejeita um registro de uma empresa informando
    obrigatoriamente o motivo da rejeição.
    """
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "plastico",
            "periodo": "2026-10",
            "volume_total": 80.0,
            "percentual_reciclado": 100.0,
        },
    )
    assert resp_criacao.status_code == 201
    registro_id = resp_criacao.json()["id"]

    token_gestor = _obter_token_gestor(client)

    # Gestor rejeita o registro informando o motivo
    motivo = "Lote contaminado com resíduos orgânicos e nota fiscal divergente."
    response = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": motivo},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert response.status_code == 200
    dados = response.json()

    assert dados["id"] == registro_id
    assert dados["status_validacao"] == "REJEITADO"
    assert dados["motivo_rejeicao"] == motivo
    assert dados["validador_id"] == "gestor-demo"
    assert dados["volume_validado"] is None
    assert dados["carbonoevitado"] is None
    assert dados["valorestimado"] is None

    # Consulta individual para confirmar a persistência
    resp_get = client.get(f"/registros/{registro_id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["status_validacao"] == "REJEITADO"
    assert resp_get.json()["motivo_rejeicao"] == motivo


def test_gestor_rejeita_registro_alias_motivo(client: TestClient):
    """
    Testa se o payload aceita 'motivo' como alias de 'motivo_rejeicao'.
    """
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "metal",
            "periodo": "2026-10",
            "volume_total": 45.0,
            "percentual_reciclado": 100.0,
        },
    )
    assert resp_criacao.status_code == 201
    registro_id = resp_criacao.json()["id"]

    token_gestor = _obter_token_gestor(client)

    response = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo": "Comprovante ilegível."},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert response.status_code == 200
    assert response.json()["status_validacao"] == "REJEITADO"
    assert response.json()["motivo_rejeicao"] == "Comprovante ilegível."


def test_gestor_rejeita_registro_sem_motivo_deve_falhar(client: TestClient):
    """
    Quando um gestor rejeita um registro de uma empresa, ele tem que
    obrigatoriamente dar um motivo para isso. O envio sem motivo ou com
    motivo em branco deve retornar erro 400.
    """
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-10",
            "volume_total": 50.0,
            "percentual_reciclado": 50.0,
        },
    )
    assert resp_criacao.status_code == 201
    registro_id = resp_criacao.json()["id"]

    token_gestor = _obter_token_gestor(client)

    # 1. Sem passar motivo no body
    resp_sem_motivo = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_sem_motivo.status_code == 400
    assert resp_sem_motivo.json()["detail"] == "O motivo da rejeição é obrigatório."

    # 2. Com string vazia
    resp_vazio = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": ""},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_vazio.status_code == 400
    assert resp_vazio.json()["detail"] == "O motivo da rejeição é obrigatório."

    # 3. Com apenas espaços em branco
    resp_espacos = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": "   "},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_espacos.status_code == 400
    assert resp_espacos.json()["detail"] == "O motivo da rejeição é obrigatório."


def test_gestor_nao_pode_rejeitar_nem_validar_registro_ja_processado(
    client: TestClient,
):
    """
    Registros já validados ou já rejeitados não podem ser processados novamente.
    """
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-10",
            "volume_total": 50.0,
            "percentual_reciclado": 50.0,
        },
    )
    registro_id = resp_criacao.json()["id"]

    token_gestor = _obter_token_gestor(client)

    # Rejeita na primeira tentativa
    resp_rej = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": "Primeira rejeicao válida."},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_rej.status_code == 200

    # Tenta rejeitar novamente
    resp_rej_novamente = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": "Segunda rejeicao."},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_rej_novamente.status_code == 400
    assert resp_rej_novamente.json()["detail"] == "Registro já processado"

    # Tenta validar o registro rejeitado
    resp_val_novamente = client.patch(
        f"/registros/{registro_id}/validar",
        json={},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_val_novamente.status_code == 400
    assert resp_val_novamente.json()["detail"] == "Registro já processado"


def test_rejeitar_registro_inexistente(client: TestClient):
    """
    Tentar rejeitar um registro inexistente deve retornar 404.
    """
    token_gestor = _obter_token_gestor(client)
    response = client.patch(
        "/registros/registro-fantasma-999/rejeitar",
        json={"motivo_rejeicao": "Qualquer motivo"},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Registro não encontrado"


def test_empresa_nao_pode_rejeitar_nem_validar_registro(client: TestClient):
    """
    Empresas comuns não têm permissão para validar ou rejeitar registros (403).
    """
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-10",
            "volume_total": 50.0,
            "percentual_reciclado": 50.0,
        },
    )
    registro_id = resp_criacao.json()["id"]

    token_empresa = _obter_token_empresa(client)

    # Empresa tenta validar
    resp_val = client.patch(
        f"/registros/{registro_id}/validar",
        json={},
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_val.status_code == 403
    assert resp_val.json()["detail"] == "Acesso restrito à Prefeitura (Superusuário)."

    # Empresa tenta rejeitar
    resp_rej = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": "Tentativa indevida"},
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_rej.status_code == 403
    assert resp_rej.json()["detail"] == "Acesso restrito à Prefeitura (Superusuário)."


def test_gestor_outra_prefeitura_nao_pode_rejeitar(client: TestClient):
    """
    Um gestor não pode rejeitar registros de uma empresa vinculada a outra prefeitura.
    """
    db = TestingSessionLocal()
    pref_b = Prefeitura(id="prefeitura-outra-rejeicao", nome="Cidade Vizinha")
    empresa_b = Empresa(
        id="empresa-outra-rejeicao",
        prefeitura_id="prefeitura-outra-rejeicao",
        cnpj="77777777000177",
        razao_social="Empresa Vizinha LTDA",
        email="vizinha@empresa.com",
        pwd_hash="hashed_123",
        empresa_status=StatusVinculo.APROVADA,
    )
    db.add(pref_b)
    db.add(empresa_b)
    db.commit()
    db.close()

    # Cria registro para a empresa de outra prefeitura
    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-outra-rejeicao",
            "material_id": "papel",
            "periodo": "2026-10",
            "volume_total": 100.0,
            "percentual_reciclado": 50.0,
        },
    )
    assert resp_criacao.status_code == 201
    registro_id = resp_criacao.json()["id"]

    token_gestor = _obter_token_gestor(client)  # Gestor de 'prefeitura-quixada'

    response = client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": "Tentando rejeitar empresa de outra cidade"},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "A empresa selecionada não está vinculada à sua prefeitura."
    )


def test_filtro_historico_por_status_rejeitado(client: TestClient):
    """
    Verifica se a listagem de registros permite filtrar por status REJEITADO
    e se o motivo da rejeição é retornado no histórico.
    """
    token_gestor = _obter_token_gestor(client)

    resp_criacao = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "vidro",
            "periodo": "2026-10",
            "volume_total": 95.0,
            "percentual_reciclado": 50.0,
        },
    )
    registro_id = resp_criacao.json()["id"]

    motivo = "Vidro misturado com cerâmica e porcelana."
    client.patch(
        f"/registros/{registro_id}/rejeitar",
        json={"motivo_rejeicao": motivo},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )

    token_empresa = _obter_token_empresa(client)
    resp_list = client.get(
        "/registros/?status_validacao=REJEITADO",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_list.status_code == 200
    registros = resp_list.json()
    assert len(registros) > 0

    rejeitado = next((r for r in registros if r["id"] == registro_id), None)
    assert rejeitado is not None
    assert rejeitado["status_validacao"] == "REJEITADO"
    assert rejeitado["motivo_rejeicao"] == motivo
    assert rejeitado["validador_id"] == "gestor-demo"


# ============================================================================
# Testes do Endpoint de Acompanhamento de Registros da Empresa
# ============================================================================


def test_empresa_acompanha_situacao_dos_seus_registros(client: TestClient):
    """
    Testa o acompanhamento da situação dos registros lançados pela empresa:
    - Registro Pendente: exibe status PENDENTE, sem motivo e sem dados de validação.
    - Registro Validado: exibe status VALIDADO, data/hora e quem validou.
    - Registro Rejeitado: exibe status REJEITADO e o motivo obrigatório.
    """
    token_empresa = _obter_token_empresa(client)
    token_gestor = _obter_token_gestor(client)

    # 1. Registro que permanecerá PENDENTE
    resp_pendente = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-10",
            "volume_total": 50.0,
            "percentual_reciclado": 60.0,
        },
    )
    assert resp_pendente.status_code == 201
    id_pendente = resp_pendente.json()["id"]

    # 2. Registro que será VALIDADO pelo gestor
    resp_validar = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "plastico",
            "periodo": "2026-10",
            "volume_total": 100.0,
            "percentual_reciclado": 80.0,
        },
    )
    assert resp_validar.status_code == 201
    id_validar = resp_validar.json()["id"]

    resp_val_gestor = client.patch(
        f"/registros/{id_validar}/validar",
        json={"volume_validado": 90.0},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_val_gestor.status_code == 200

    # 3. Registro que será REJEITADO pelo gestor
    resp_rejeitar = client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "metal",
            "periodo": "2026-10",
            "volume_total": 70.0,
            "percentual_reciclado": 50.0,
        },
    )
    assert resp_rejeitar.status_code == 201
    id_rejeitar = resp_rejeitar.json()["id"]

    motivo_recusa = "Contaminação com óleo e resíduos perigosos."
    resp_rej_gestor = client.patch(
        f"/registros/{id_rejeitar}/rejeitar",
        json={"motivo_rejeicao": motivo_recusa},
        headers={"Authorization": f"Bearer {token_gestor}"},
    )
    assert resp_rej_gestor.status_code == 200

    # 4. Empresa consulta o acompanhamento de seus registros
    response = client.get(
        "/registros/acompanhamento",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert response.status_code == 200
    lista = response.json()
    assert len(lista) >= 3

    # Mapeia pelos IDs para validações precisas
    mapa = {r["id"]: r for r in lista}

    # Valida registro Pendente
    reg_pendente = mapa[id_pendente]
    assert reg_pendente["status"] == "PENDENTE"
    assert reg_pendente["status_validacao"] == "PENDENTE"
    assert reg_pendente["motivo_rejeicao"] is None
    assert reg_pendente["motivo"] is None
    assert reg_pendente["data_validacao"] is None
    assert reg_pendente["validador_nome"] is None

    # Valida registro Validado
    reg_validado = mapa[id_validar]
    assert reg_validado["status"] == "VALIDADO"
    assert reg_validado["status_validacao"] == "VALIDADO"
    assert reg_validado["motivo_rejeicao"] is None
    assert reg_validado["data_validacao"] is not None
    assert reg_validado["validador_nome"] == "Gestor Demo"
    assert reg_validado["nome_validador"] == "Gestor Demo"
    assert reg_validado["volume_validado"] == 90.0

    # Valida registro Rejeitado
    reg_rejeitado = mapa[id_rejeitar]
    assert reg_rejeitado["status"] == "REJEITADO"
    assert reg_rejeitado["status_validacao"] == "REJEITADO"
    assert reg_rejeitado["motivo_rejeicao"] == motivo_recusa
    assert reg_rejeitado["motivo"] == motivo_recusa
    assert reg_rejeitado["data_validacao"] is None
    assert reg_rejeitado["validador_nome"] is None


def test_empresa_acompanhamento_filtro_status(client: TestClient):
    """
    Testa a filtragem dos registros pelo status (VALIDADO, REJEITADO, PENDENTE).
    Aceita termos em minúsculo e maiúsculo.
    """
    token_empresa = _obter_token_empresa(client)

    # Filtrar por status=validado
    resp_val = client.get(
        "/registros/acompanhamento?status=validado",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_val.status_code == 200
    itens_val = resp_val.json()
    assert len(itens_val) > 0
    for item in itens_val:
        assert item["status_validacao"] == "VALIDADO"
        assert item["data_validacao"] is not None
        assert item["validador_nome"] is not None

    # Filtrar por status=rejeitado
    resp_rej = client.get(
        "/registros/acompanhamento?status=rejeitado",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_rej.status_code == 200
    itens_rej = resp_rej.json()
    assert len(itens_rej) > 0
    for item in itens_rej:
        assert item["status_validacao"] == "REJEITADO"
        assert item["motivo_rejeicao"] is not None

    # Filtrar por status=pendente
    resp_pen = client.get(
        "/registros/acompanhamento?status=pendente",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_pen.status_code == 200
    itens_pen = resp_pen.json()
    assert len(itens_pen) > 0
    for item in itens_pen:
        assert item["status_validacao"] == "PENDENTE"


def test_empresa_acompanhamento_filtro_periodo(client: TestClient):
    """
    Testa a filtragem por período de tempo no endpoint de acompanhamento.
    """
    token_empresa = _obter_token_empresa(client)

    # Cria registros com períodos distintos
    client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-05",
            "volume_total": 40.0,
            "percentual_reciclado": 50.0,
        },
    )
    client.post(
        "/registros/",
        json={
            "empresa_id": "empresa-demo",
            "material_id": "papel",
            "periodo": "2026-06",
            "volume_total": 55.0,
            "percentual_reciclado": 50.0,
        },
    )

    # Filtra período exato 2026-05
    resp_p = client.get(
        "/registros/acompanhamento?periodo=2026-05",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_p.status_code == 200
    itens_p = resp_p.json()
    assert len(itens_p) > 0
    assert all(i["periodo"] == "2026-05" for i in itens_p)

    # Filtra faixa de período (2026-05 a 2026-06)
    resp_faixa = client.get(
        "/registros/acompanhamento?periodo_inicio=2026-05&periodo_fim=2026-06",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_faixa.status_code == 200
    itens_faixa = resp_faixa.json()
    assert len(itens_faixa) >= 2
    assert all(i["periodo"] in ("2026-05", "2026-06") for i in itens_faixa)


def test_empresa_acompanhamento_aliases_e_seguranca(client: TestClient):
    """
    Testa rota alias /registros/empresa e garante que sem autenticação
    e sem empresa_id retorne 401.
    """
    token_empresa = _obter_token_empresa(client)

    # Rota alias /registros/empresa
    resp_alias = client.get(
        "/registros/empresa",
        headers={"Authorization": f"Bearer {token_empresa}"},
    )
    assert resp_alias.status_code == 200
    assert isinstance(resp_alias.json(), list)

    # Sem autenticação e sem empresa_id -> 401
    resp_unauth = client.get("/registros/acompanhamento")
    assert resp_unauth.status_code == 401


# ============================================================================
# Testes de Estatísticas e Dashboard Completo
# ============================================================================


def test_dashboard_e_estatisticas_completas(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "src.services.services.obter_cotacao_dolar", lambda *_args, **_kw: 5.0
    )

    token_gestor = _obter_token_gestor(client)
    token_empresa = _obter_token_empresa(client)
    headers_gestor = {"Authorization": f"Bearer {token_gestor}"}
    headers_empresa = {"Authorization": f"Bearer {token_empresa}"}

    # Sem autenticação -> 401
    assert client.get("/dashboard/").status_code == 401
    assert client.get("/registros/estatisticas/resumo").status_code == 401
    assert client.get("/registros/estatisticas/status").status_code == 401
    assert client.get("/registros/estatisticas/por-material").status_code == 401
    assert client.get("/registros/estatisticas/por-periodo").status_code == 401
    assert client.get("/registros/estatisticas/por-empresa").status_code == 401
    assert client.get("/empresas/estatisticas/ranking").status_code == 401

    # Empresa não pode acessar rotas exclusivas da prefeitura -> 403
    assert (
        client.get(
            "/registros/estatisticas/por-empresa", headers=headers_empresa
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/empresas/estatisticas/ranking", headers=headers_empresa
        ).status_code
        == 403
    )

    # Resumo geral da prefeitura
    resp_resumo = client.get("/registros/estatisticas/resumo", headers=headers_gestor)
    assert resp_resumo.status_code == 200
    resumo = resp_resumo.json()
    assert resumo["total_registros"] == (
        resumo["registros_pendentes"]
        + resumo["registros_validados"]
        + resumo["registros_rejeitados"]
    )
    assert resumo["volume_total_declarado"] > 0
    assert resumo["volume_total_validado"] > 0
    assert resumo["carbono_total_evitado"] > 0
    assert resumo["valor_total_estimado"] > 0

    # Contagem por status
    resp_status = client.get("/registros/estatisticas/status", headers=headers_gestor)
    assert resp_status.status_code == 200
    contagens_status = resp_status.json()
    assert set(contagens_status) >= {"PENDENTE", "VALIDADO", "REJEITADO"}
    assert contagens_status["VALIDADO"] == resumo["registros_validados"]

    # Detalhamento por material
    resp_mat = client.get(
        "/registros/estatisticas/por-material", headers=headers_gestor
    )
    assert resp_mat.status_code == 200
    materiais = resp_mat.json()
    assert len(materiais) >= 2
    assert {m["material_id"] for m in materiais} >= {"papel", "plastico"}

    # Evolução por período
    resp_per = client.get(
        "/registros/estatisticas/por-periodo?periodo_inicio=2026-05&periodo_fim=2026-10",
        headers=headers_gestor,
    )
    assert resp_per.status_code == 200
    periodos = resp_per.json()
    assert len(periodos) >= 2
    assert [p["periodo"] for p in periodos] == sorted(p["periodo"] for p in periodos)

    # Ranking de empresas (prefeitura)
    resp_rank = client.get("/empresas/estatisticas/ranking", headers=headers_gestor)
    assert resp_rank.status_code == 200
    ranking = resp_rank.json()
    assert any(item["empresa_id"] == "empresa-demo" for item in ranking)
    assert all(item["empresa_id"] != "empresa-quixeramobim" for item in ranking)

    resp_por_emp = client.get(
        "/registros/estatisticas/por-empresa", headers=headers_gestor
    )
    assert resp_por_emp.status_code == 200
    assert resp_por_emp.json() == ranking

    # Dashboard consolidado (visão Prefeitura)
    resp_dash_pref = client.get("/dashboard/", headers=headers_gestor)
    assert resp_dash_pref.status_code == 200
    dash_pref = resp_dash_pref.json()
    assert dash_pref["escopo"] == "PREFEITURA"
    assert dash_pref["empresas_por_status"] is not None
    assert dash_pref["empresas_por_status"]["APROVADA"] >= 1
    assert dash_pref["total_empresas"] >= 1
    assert dash_pref["resumo_registros"] == resumo
    assert len(dash_pref["por_material"]) >= 2
    assert len(dash_pref["por_periodo"]) >= 2
    assert len(dash_pref["ranking_empresas"]) >= 1

    # Dashboard consolidado (visão Empresa: isolada aos próprios dados)
    resp_dash_emp = client.get("/dashboard/resumo", headers=headers_empresa)
    assert resp_dash_emp.status_code == 200
    dash_emp = resp_dash_emp.json()
    assert dash_emp["escopo"] == "EMPRESA"
    assert dash_emp["empresas_por_status"] is None
    assert dash_emp["total_empresas"] is None
    assert dash_emp["ranking_empresas"] == []
    assert dash_emp["resumo_registros"]["total_registros"] > 0
