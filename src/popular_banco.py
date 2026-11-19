"""
Popula o banco com dados de demonstração: empresas nos dois municípios, em
todas as situações de vínculo, materiais cadastrados pelas prefeituras e
lançamentos dos últimos 12 meses em todos os status, com histórico.

Uso: uv run python -m src.popular_banco

As contas do seed (empresa@demo.com, gestor@demo.com, empresa2@demo.com e
gestor2@demo.com) continuam vindo do seed_dev.sql. Todas as contas usam a
senha demo123.
"""

import random
from datetime import UTC, date, datetime, timedelta

from loguru import logger

from src.app import inicializar_banco
from src.core.database import SessionLocal
from src.models.models import (
    Empresa,
    HistoricoCadastro,
    HistoricoRegistro,
    Material,
    Registro,
    UsuarioAdmin,
)
from src.schemas.enums import AcaoHistoricoRegistro, StatusValidacao, StatusVinculo
from src.schemas.validacao import digito_verificador_cnpj
from src.services.services import VALOR_TONELADA_CO2_USD, obter_cotacao_dolar

HASH_DEMO123 = "$2b$12$EewUZscvfTEMpkYELJXRruH5oYa4ztKO8qr7K34pqpwlQgUbGLCwG"
QUIXADA = "prefeitura-quixada"
QUIXERAMOBIM = "prefeitura-quixeramobim"
MARCADOR = "empresa-coopsertao"

FAIXAS_DE_VOLUME = {
    "papel": (6.0, 22.0),
    "plastico": (2.5, 9.0),
    "vidro": (1.5, 6.0),
    "metal": (0.8, 4.0),
    "material-oleo-quixada": (0.3, 1.2),
    "material-isopor-quixada": (0.2, 0.9),
    "material-pneus-quixeramobim": (1.0, 4.5),
}

MOTIVOS_REJEICAO = [
    "O ticket da balança não confere com o volume informado.",
    "Volume muito acima da média da empresa, sem comprovante.",
    "Material lançado não corresponde ao recebido no ecoponto.",
]

MOTIVOS_CORRECAO = [
    "Envie o volume do ticket da balança; o informado está arredondado.",
    "O percentual reciclado parece alto para este material. Confira.",
]

EMPRESAS = [
    {
        "id": "empresa-coopsertao",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100220001",
        "razao_social": "Cooperativa de Catadores do Sertão Central",
        "nome_fantasia": "Coopsertão",
        "email": "coopsertao@demo.com",
        "telefone": "8834121010",
        "endereco": "Rua José Jucá, 410, Campo Velho, Quixadá - CE",
        "status": StatusVinculo.APROVADA,
        "materiais": [
            "papel",
            "plastico",
            "vidro",
            "metal",
            "material-oleo-quixada",
        ],
        "escala": 1.6,
    },
    {
        "id": "empresa-recicla-quixada",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100330001",
        "razao_social": "Recicla Quixadá Comércio de Sucatas LTDA",
        "nome_fantasia": "Recicla Quixadá",
        "email": "reciclaquixada@demo.com",
        "telefone": "88999021122",
        "endereco": "Av. Plácido Castelo, 1520, Planalto Universitário, Quixadá - CE",
        "status": StatusVinculo.APROVADA,
        "materiais": ["metal", "plastico"],
        "escala": 1.0,
    },
    {
        "id": "empresa-vidro-limpo",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100440001",
        "razao_social": "Vidro Limpo Reciclagem LTDA",
        "nome_fantasia": "Vidro Limpo",
        "email": "vidrolimpo@demo.com",
        "telefone": "8834123344",
        "endereco": "Rua Epitácio Pessoa, 88, Centro, Quixadá - CE",
        "status": StatusVinculo.APROVADA,
        "materiais": ["vidro"],
        "escala": 1.2,
    },
    {
        "id": "empresa-ecoponto-cedro",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100550001",
        "razao_social": "Associação Ecoponto Cedro",
        "nome_fantasia": "Ecoponto Cedro",
        "email": "ecopontocedro@demo.com",
        "telefone": "88998123456",
        "endereco": "Estrada do Açude do Cedro, s/n, Cedro, Quixadá - CE",
        "status": StatusVinculo.APROVADA,
        "materiais": ["papel", "plastico", "material-isopor-quixada"],
        "escala": 0.6,
        "pede_desassociacao": "A associação vai se fundir com a Coopsertão.",
    },
    {
        "id": "empresa-sucata-monolitos",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100660001",
        "razao_social": "Sucata Monólitos LTDA",
        "nome_fantasia": "Sucata Monólitos",
        "email": "sucatamonolitos@demo.com",
        "telefone": "8834125566",
        "endereco": "Rua Basílio Pinto, 230, Centro, Quixadá - CE",
        "status": StatusVinculo.DESASSOCIADA,
        "materiais": ["metal", "papel"],
        "escala": 0.8,
        "ate_meses_atras": 4,
    },
    {
        "id": "empresa-papel-e-cia",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100770001",
        "razao_social": "Papel & Cia Reciclagem LTDA",
        "nome_fantasia": "Papel & Cia",
        "email": "papelecia@demo.com",
        "telefone": "88997654321",
        "endereco": "Rua Tenente Cravo, 15, Combate, Quixadá - CE",
        "status": StatusVinculo.AGUARDANDO_VALIDACAO,
        "email_confirmado": True,
    },
    {
        "id": "empresa-plastico-verde",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100880001",
        "razao_social": "Plástico Verde Indústria LTDA",
        "nome_fantasia": None,
        "email": "plasticoverde@demo.com",
        "status": StatusVinculo.AGUARDANDO_VALIDACAO,
        "email_confirmado": False,
    },
    {
        "id": "empresa-transportes-banabuiu",
        "prefeitura_id": QUIXADA,
        "base_cnpj": "331100990001",
        "razao_social": "Transportes Banabuiú LTDA",
        "nome_fantasia": "Banabuiú Transportes",
        "email": "banabuiu@demo.com",
        "status": StatusVinculo.RECUSADA,
        "motivo_recusa": (
            "O CNPJ é de transportadora e não tem atividade de reciclagem "
            "cadastrada na Receita."
        ),
    },
    {
        "id": "empresa-coopquix",
        "prefeitura_id": QUIXERAMOBIM,
        "base_cnpj": "441100110001",
        "razao_social": "Cooperativa Recicla Sertão de Quixeramobim",
        "nome_fantasia": "Coopquix",
        "email": "coopquix@demo.com",
        "telefone": "8834411020",
        "endereco": "Rua Cônego Pinto, 300, Centro, Quixeramobim - CE",
        "status": StatusVinculo.APROVADA,
        "materiais": ["papel", "plastico", "vidro", "material-pneus-quixeramobim"],
        "escala": 1.1,
    },
    {
        "id": "empresa-metais-boa-viagem",
        "prefeitura_id": QUIXERAMOBIM,
        "base_cnpj": "441100220001",
        "razao_social": "Metais Boa Viagem LTDA",
        "nome_fantasia": "Metais Boa Viagem",
        "email": "metaisboaviagem@demo.com",
        "status": StatusVinculo.AGUARDANDO_VALIDACAO,
        "email_confirmado": True,
    },
]

COM_PEDIDO_DE_CORRECAO = {"empresa-demo", "empresa-coopsertao", "empresa-coopquix"}

MATERIAIS_DAS_EMPRESAS_DO_SEED = {
    "empresa-demo": (["papel", "plastico", "metal"], 0.9),
    "empresa-quixeramobim": (["papel", "plastico", "metal"], 0.8),
}

MATERIAIS_DAS_PREFEITURAS = [
    ("material-oleo-quixada", "Óleo de cozinha usado", 1.2, QUIXADA),
    ("material-isopor-quixada", "Isopor", 0.8, QUIXADA),
    ("material-pneus-quixeramobim", "Pneus", 1.1, QUIXERAMOBIM),
]


def cnpj_valido(base: str) -> str:
    primeiro = digito_verificador_cnpj(base)
    return base + primeiro + digito_verificador_cnpj(base + primeiro)


def meses_ate_hoje(hoje: date, quantidade: int) -> list[tuple[int, int]]:
    meses = []
    ano, mes = hoje.year, hoje.month
    for _ in range(quantidade):
        meses.append((ano, mes))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    return list(reversed(meses))


def momento(ano: int, mes: int, dia: int, sorteio: random.Random) -> datetime:
    return datetime(
        ano, mes, dia, sorteio.randint(7, 17), sorteio.randint(0, 59), tzinfo=UTC
    )


class Populador:
    def __init__(self, db, sorteio: random.Random, hoje: date, cotacao: float):
        self.db = db
        self.sorteio = sorteio
        self.hoje = hoje
        self.cotacao = cotacao
        self.gestores = {
            admin.id_prefeitura: admin for admin in db.query(UsuarioAdmin).all()
        }
        self.fatores = {m.id: m.fator_emissaoipcc for m in db.query(Material).all()}

    def criar_materiais(self) -> None:
        for material_id, categoria, fator, prefeitura_id in MATERIAIS_DAS_PREFEITURAS:
            self.db.add(
                Material(
                    id=material_id,
                    categoria=categoria,
                    fator_emissaoipcc=fator,
                    prefeitura_id=prefeitura_id,
                )
            )
            self.fatores[material_id] = fator

    def criar_empresa(self, dados: dict) -> Empresa:
        cadastro = momento(
            self.hoje.year - 1, self.hoje.month, 2, self.sorteio
        ) - timedelta(days=self.sorteio.randint(0, 20))
        if dados["status"] == StatusVinculo.AGUARDANDO_VALIDACAO:
            cadastro = datetime.now(UTC) - timedelta(days=self.sorteio.randint(1, 6))

        empresa = Empresa(
            id=dados["id"],
            prefeitura_id=dados["prefeitura_id"],
            cnpj=cnpj_valido(dados["base_cnpj"]),
            razao_social=dados["razao_social"],
            nome_fantasia=dados.get("nome_fantasia"),
            email=dados["email"],
            telefone=dados.get("telefone"),
            endereco=dados.get("endereco"),
            pwd_hash=HASH_DEMO123,
            empresa_status=dados["status"],
            email_confirmado=dados.get("email_confirmado", True),
            motivo_recusa=dados.get("motivo_recusa"),
            created_at=cadastro,
            updated_at=cadastro,
        )
        self.db.add(empresa)

        if dados["status"] == StatusVinculo.DESASSOCIADA:
            gestor = self.gestores[dados["prefeitura_id"]]
            saida = datetime.now(UTC) - timedelta(days=55)
            empresa.deleted_at = saida
            self.historico_cadastro(
                empresa,
                "desassociacao_solicitada",
                "false",
                "Encerramos as atividades de reciclagem.",
                empresa,
                saida - timedelta(days=3),
            )
            self.historico_cadastro(
                empresa,
                "empresa_status",
                StatusVinculo.APROVADA.value,
                StatusVinculo.DESASSOCIADA.value,
                gestor,
                saida,
            )

        if dados.get("pede_desassociacao"):
            pedido = datetime.now(UTC) - timedelta(days=2)
            empresa.desassociacao_solicitada = True
            empresa.motivo_desassociacao = dados["pede_desassociacao"]
            empresa.data_solicitacao_desassociacao = pedido
            self.historico_cadastro(
                empresa,
                "desassociacao_solicitada",
                "false",
                dados["pede_desassociacao"],
                empresa,
                pedido,
            )
        return empresa

    def historico_cadastro(self, empresa, campo, anterior, novo, autor, quando):
        nome = getattr(autor, "nome", None) or (
            autor.nome_fantasia or autor.razao_social
        )
        self.db.add(
            HistoricoCadastro(
                empresa_id=empresa.id,
                autor_id=autor.id,
                autor_nome=nome,
                campo=campo,
                valor_anterior=anterior,
                valor_novo=novo,
                created_at=quando,
                updated_at=quando,
            )
        )

    def historico_registro(self, registro, empresa_nome, autor, campo, antes, depois):
        nome = getattr(autor, "nome", None) or empresa_nome
        self.db.add(
            HistoricoRegistro(
                registro_id=registro.id,
                empresa_id=registro.empresa_id,
                autor_id=autor.id,
                autor_nome=nome,
                acao=AcaoHistoricoRegistro.EDICAO,
                campo=campo,
                valor_anterior=antes,
                valor_novo=depois,
                created_at=registro.updated_at,
                updated_at=registro.updated_at,
            )
        )

    def validar(self, registro: Registro, gestor, volume: float, quando: datetime):
        carbono = (
            volume
            * (registro.percentual_reciclado / 100)
            * self.fatores[registro.material_id]
        )
        registro.status_validacao = StatusValidacao.VALIDADO
        registro.volume_validado = volume
        registro.carbonoevitado = carbono
        registro.valorestimado = round(
            carbono * VALOR_TONELADA_CO2_USD * self.cotacao, 2
        )
        registro.validador_id = gestor.id
        registro.data_validacao = quando
        registro.updated_at = quando

    def lancamentos(self, empresa: Empresa, materiais, escala, ate_meses_atras=0):
        gestor = self.gestores[empresa.prefeitura_id]
        nome = empresa.nome_fantasia or empresa.razao_social
        meses = meses_ate_hoje(self.hoje, 12)
        if ate_meses_atras:
            meses = meses[:-ate_meses_atras]

        for indice, (ano, mes) in enumerate(meses):
            mes_atual = (ano, mes) == (self.hoje.year, self.hoje.month)
            ultimo_dia = self.hoje.day if mes_atual else 28
            for material_id in materiais:
                if self.sorteio.random() < 0.15 and not mes_atual:
                    continue
                minimo, maximo = FAIXAS_DE_VOLUME[material_id]
                sazonal = 1 + 0.25 * ((indice % 12) in (10, 11))
                volume = round(
                    self.sorteio.uniform(minimo, maximo) * escala * sazonal, 2
                )
                dia = self.sorteio.randint(1, max(1, ultimo_dia))
                criado = min(
                    momento(ano, mes, dia, self.sorteio),
                    datetime.now(UTC) - timedelta(minutes=30),
                )
                pela_prefeitura = self.sorteio.random() < 0.12

                registro = Registro(
                    empresa_id=empresa.id,
                    material_id=material_id,
                    periodo=f"{ano}-{mes:02d}",
                    volume_total_original=volume,
                    percentual_reciclado=float(self.sorteio.randint(72, 97)),
                    status_validacao=StatusValidacao.PENDENTE,
                    criado_por_gestor_id=gestor.id if pela_prefeitura else None,
                    created_at=criado,
                    updated_at=criado,
                )
                self.db.add(registro)
                self.db.flush()

                if pela_prefeitura:
                    self.validar(registro, gestor, volume, criado)
                    continue

                dias_desde = (self.hoje - criado.date()).days
                sorteio = self.sorteio.random()
                if dias_desde <= 3 or (mes_atual and sorteio < 0.5):
                    continue

                validado_em = criado + timedelta(days=self.sorteio.randint(1, 3))
                if sorteio < 0.07:
                    registro.status_validacao = StatusValidacao.REJEITADO
                    registro.motivo_rejeicao = self.sorteio.choice(MOTIVOS_REJEICAO)
                    registro.validador_id = gestor.id
                    registro.data_validacao = validado_em
                    registro.updated_at = validado_em
                elif sorteio < 0.17:
                    conferido = round(volume * self.sorteio.uniform(0.88, 0.97), 2)
                    self.validar(registro, gestor, conferido, validado_em)
                else:
                    self.validar(registro, gestor, volume, validado_em)

        self.corrigido_depois_de_rejeitado(empresa, gestor, nome)
        if empresa.id in COM_PEDIDO_DE_CORRECAO:
            self.correcao_pendente(empresa, gestor)

    def pedir_correcao(self, registro, gestor, criado):
        quando = min(criado + timedelta(days=1), datetime.now(UTC))
        motivo = self.sorteio.choice(MOTIVOS_CORRECAO)
        registro.correcao_solicitada = True
        registro.motivo_correcao = motivo
        registro.data_solicitacao_correcao = quando
        registro.updated_at = quando
        self.historico_registro(
            registro, None, gestor, "correcao_solicitada", None, motivo
        )

    def correcao_pendente(self, empresa, gestor):
        criado = datetime.now(UTC) - timedelta(days=self.sorteio.randint(2, 5))
        registro = Registro(
            empresa_id=empresa.id,
            material_id="plastico",
            periodo=f"{self.hoje.year}-{self.hoje.month:02d}",
            volume_total_original=round(self.sorteio.uniform(4, 9)),
            percentual_reciclado=98.0,
            status_validacao=StatusValidacao.PENDENTE,
            created_at=criado,
            updated_at=criado,
        )
        self.db.add(registro)
        self.db.flush()
        self.pedir_correcao(registro, gestor, criado)

    def corrigido_depois_de_rejeitado(self, empresa, gestor, nome):
        if empresa.empresa_status != StatusVinculo.APROVADA:
            return
        material_id = "papel" if empresa.id != "empresa-vidro-limpo" else "vidro"
        criado = datetime.now(UTC) - timedelta(days=self.sorteio.randint(4, 8))
        rejeitado = criado + timedelta(days=1)
        corrigido = rejeitado + timedelta(days=1)
        volume = round(self.sorteio.uniform(*FAIXAS_DE_VOLUME[material_id]), 2)
        corrigido_volume = round(volume * 0.93, 2)

        registro = Registro(
            empresa_id=empresa.id,
            material_id=material_id,
            periodo=f"{self.hoje.year}-{self.hoje.month:02d}",
            volume_total_original=corrigido_volume,
            percentual_reciclado=85.0,
            status_validacao=StatusValidacao.PENDENTE,
            created_at=criado,
            updated_at=corrigido,
        )
        self.db.add(registro)
        self.db.flush()
        self.historico_registro(
            registro,
            nome,
            empresa,
            "volume_total",
            f"{volume:g}",
            f"{corrigido_volume:g}",
        )
        self.historico_registro(
            registro,
            nome,
            empresa,
            "status_validacao",
            StatusValidacao.REJEITADO.value,
            StatusValidacao.PENDENTE.value,
        )


def popular() -> None:
    inicializar_banco()
    db = SessionLocal()
    try:
        if db.get(Empresa, MARCADOR):
            logger.info("O banco já tem os dados de demonstração. Nada a fazer.")
            return
        if not db.get(Empresa, "empresa-demo"):
            raise RuntimeError(
                "As contas de demonstração não estão no banco. "
                "Rode com SEED_DEV_DATA=true para aplicar o seed_dev.sql."
            )

        populador = Populador(
            db, random.Random(2026), date.today(), obter_cotacao_dolar()
        )
        populador.criar_materiais()

        for dados in EMPRESAS:
            empresa = populador.criar_empresa(dados)
            if dados.get("materiais"):
                populador.lancamentos(
                    empresa,
                    dados["materiais"],
                    dados["escala"],
                    dados.get("ate_meses_atras", 0),
                )

        for empresa_id, (materiais, escala) in MATERIAIS_DAS_EMPRESAS_DO_SEED.items():
            populador.lancamentos(db.get(Empresa, empresa_id), materiais, escala)

        db.commit()
        logger.info(
            f"Dados de demonstração criados: {db.query(Empresa).count()} empresas "
            f"e {db.query(Registro).count()} lançamentos."
        )
    finally:
        db.close()


if __name__ == "__main__":
    popular()
