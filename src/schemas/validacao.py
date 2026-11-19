import math
import re
from datetime import date

from pydantic_core import PydanticCustomError

RAZAO_SOCIAL_MIN = 3
RAZAO_SOCIAL_MAX = 150
NOME_FANTASIA_MAX = 100
ENDERECO_MAX = 200
TELEFONE_DIGITOS = (10, 11)
MOTIVO_RECUSA_MIN = 5
MOTIVO_RECUSA_MAX = 500
PERCENTUAL_MIN = 0
PERCENTUAL_MAX = 100
VOLUME_MAX = 100_000
PERIODO_MIN = (2000, 1)
CATEGORIA_MATERIAL_MIN = 2
CATEGORIA_MATERIAL_MAX = 60
FATOR_EMISSAO_CASAS = 2
PADRAO_PERIODO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PADRAO_CNPJ = re.compile(r"^[0-9A-Z]{12}\d{2}$")

PESOS_CNPJ = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def digito_verificador_cnpj(base: str) -> str:
    pesos = PESOS_CNPJ[-len(base) :]
    resto = sum((ord(c) - 48) * p for c, p in zip(base, pesos, strict=True)) % 11
    return "0" if resto < 2 else str(11 - resto)


def normalizar_cnpj(valor: str) -> str:
    cnpj = re.sub(r"[\s./-]", "", valor).upper()
    if not PADRAO_CNPJ.match(cnpj) or len(set(cnpj)) == 1:
        raise PydanticCustomError("cnpj_invalido", "CNPJ inválido.")

    primeiro = digito_verificador_cnpj(cnpj[:12])
    segundo = digito_verificador_cnpj(cnpj[:12] + primeiro)
    if cnpj[12:] != primeiro + segundo:
        raise PydanticCustomError("cnpj_invalido", "CNPJ inválido.")

    return cnpj


def normalizar_email(valor: str | None) -> str | None:
    return None if valor is None else valor.strip().lower()


def validar_razao_social(valor: str | None) -> str:
    texto = (valor or "").strip()
    if not texto:
        raise PydanticCustomError("razao_social_obrigatoria", "Informe a razão social.")
    if not RAZAO_SOCIAL_MIN <= len(texto) <= RAZAO_SOCIAL_MAX:
        raise PydanticCustomError(
            "razao_social_tamanho",
            f"A razão social deve ter entre {RAZAO_SOCIAL_MIN} e "
            f"{RAZAO_SOCIAL_MAX} caracteres.",
        )
    return texto


def texto_opcional(valor: str | None, maximo: int, mensagem: str) -> str | None:
    if valor is None:
        return None
    texto = valor.strip()
    if len(texto) > maximo:
        raise PydanticCustomError("texto_longo", mensagem)
    return texto or None


def validar_nome_fantasia(valor: str | None) -> str | None:
    return texto_opcional(
        valor,
        NOME_FANTASIA_MAX,
        f"O nome fantasia deve ter no máximo {NOME_FANTASIA_MAX} caracteres.",
    )


def validar_endereco(valor: str | None) -> str | None:
    return texto_opcional(
        valor,
        ENDERECO_MAX,
        f"O endereço deve ter no máximo {ENDERECO_MAX} caracteres.",
    )


def validar_telefone(valor: str | None) -> str | None:
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", valor)
    if not digitos:
        return None
    if len(digitos) not in TELEFONE_DIGITOS:
        raise PydanticCustomError(
            "telefone_invalido",
            "Informe o telefone com DDD (10 ou 11 dígitos).",
        )
    return digitos


def validar_motivo_recusa(valor: str | None) -> str | None:
    if valor is None:
        return None
    texto = valor.strip()
    if not MOTIVO_RECUSA_MIN <= len(texto) <= MOTIVO_RECUSA_MAX:
        raise PydanticCustomError(
            "motivo_recusa_tamanho",
            f"O motivo da recusa deve ter entre {MOTIVO_RECUSA_MIN} e "
            f"{MOTIVO_RECUSA_MAX} caracteres.",
        )
    return texto


def _motivo_opcional(valor: str | None, codigo: str, rotulo: str) -> str | None:
    if valor is None:
        return None
    texto = valor.strip()
    if not texto:
        return None
    if not MOTIVO_RECUSA_MIN <= len(texto) <= MOTIVO_RECUSA_MAX:
        raise PydanticCustomError(
            codigo,
            f"{rotulo} deve ter entre {MOTIVO_RECUSA_MIN} e "
            f"{MOTIVO_RECUSA_MAX} caracteres.",
        )
    return texto


def validar_motivo_rejeicao(valor: str | None) -> str | None:
    return _motivo_opcional(valor, "motivo_rejeicao_tamanho", "O motivo da rejeição")


def validar_justificativa_correcao(valor: str | None) -> str | None:
    return _motivo_opcional(
        valor, "justificativa_correcao_tamanho", "A justificativa da correção"
    )


def validar_periodo(valor: str) -> str:
    if not PADRAO_PERIODO.match(valor):
        raise PydanticCustomError(
            "periodo_invalido", "Informe o período no formato AAAA-MM."
        )
    ano, mes = (int(parte) for parte in valor.split("-"))
    if (ano, mes) < PERIODO_MIN:
        raise PydanticCustomError(
            "periodo_antigo",
            f"O período deve ser a partir de {PERIODO_MIN[0]}-{PERIODO_MIN[1]:02d}.",
        )
    hoje = date.today()
    if (ano, mes) > (hoje.year, hoje.month):
        raise PydanticCustomError(
            "periodo_futuro", "O período não pode estar no futuro."
        )
    return valor


def validar_volume(valor: float) -> float:
    if not math.isfinite(valor) or valor <= 0:
        raise PydanticCustomError(
            "volume_invalido", "O volume deve ser maior que zero."
        )
    if valor > VOLUME_MAX:
        raise PydanticCustomError(
            "volume_alto",
            f"O volume deve ser de no máximo {VOLUME_MAX:,} t.".replace(",", "."),
        )
    return valor


def validar_percentual(valor: float) -> float:
    if not math.isfinite(valor) or not PERCENTUAL_MIN <= valor <= PERCENTUAL_MAX:
        raise PydanticCustomError(
            "percentual_invalido",
            f"O percentual reciclado deve estar entre {PERCENTUAL_MIN} e "
            f"{PERCENTUAL_MAX}.",
        )
    return valor


def validar_categoria_material(valor: str) -> str:
    texto = valor.strip()
    if not CATEGORIA_MATERIAL_MIN <= len(texto) <= CATEGORIA_MATERIAL_MAX:
        raise PydanticCustomError(
            "categoria_tamanho",
            f"O nome do material deve ter entre {CATEGORIA_MATERIAL_MIN} e "
            f"{CATEGORIA_MATERIAL_MAX} caracteres.",
        )
    return texto


def validar_fator_emissao(valor: float) -> float:
    if not math.isfinite(valor) or valor <= 0:
        raise PydanticCustomError(
            "fator_invalido", "O fator de emissão deve ser maior que zero."
        )
    if round(valor, FATOR_EMISSAO_CASAS) != valor:
        raise PydanticCustomError(
            "fator_casas",
            f"Use no máximo {FATOR_EMISSAO_CASAS} casas decimais no fator de emissão.",
        )
    return valor
