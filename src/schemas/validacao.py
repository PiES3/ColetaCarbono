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
PADRAO_PERIODO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

PESOS_CNPJ = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def digito_verificador_cnpj(digitos: str) -> str:
    pesos = PESOS_CNPJ[-len(digitos) :]
    resto = sum(int(d) * p for d, p in zip(digitos, pesos, strict=True)) % 11
    return "0" if resto < 2 else str(11 - resto)


def normalizar_cnpj(valor: str) -> str:
    digitos = re.sub(r"\D", "", valor)
    if len(digitos) != 14 or len(set(digitos)) == 1:
        raise PydanticCustomError("cnpj_invalido", "CNPJ inválido.")

    primeiro = digito_verificador_cnpj(digitos[:12])
    segundo = digito_verificador_cnpj(digitos[:12] + primeiro)
    if digitos[12:] != primeiro + segundo:
        raise PydanticCustomError("cnpj_invalido", "CNPJ inválido.")

    return digitos


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


def validar_periodo(valor: str) -> str:
    if not PADRAO_PERIODO.match(valor):
        raise PydanticCustomError(
            "periodo_invalido", "Informe o período no formato AAAA-MM."
        )
    ano, mes = (int(parte) for parte in valor.split("-"))
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
    return valor


def validar_percentual(valor: float) -> float:
    if not math.isfinite(valor) or not PERCENTUAL_MIN <= valor <= PERCENTUAL_MAX:
        raise PydanticCustomError(
            "percentual_invalido",
            f"O percentual reciclado deve estar entre {PERCENTUAL_MIN} e "
            f"{PERCENTUAL_MAX}.",
        )
    return valor
