from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

MENSAGENS_PADRAO = {
    "missing": "Campo obrigatório.",
    "string_type": "Informe um texto.",
    "float_parsing": "Informe um número válido.",
    "float_type": "Informe um número válido.",
    "finite_number": "Informe um número válido.",
    "int_parsing": "Informe um número inteiro.",
    "int_type": "Informe um número inteiro.",
    "bool_parsing": "Informe verdadeiro ou falso.",
    "bool_type": "Informe verdadeiro ou falso.",
    "enum": "Valor inválido.",
    "literal_error": "Valor inválido.",
    "list_type": "Informe uma lista.",
    "dict_type": "Informe um objeto.",
    "model_attributes_type": "Informe um objeto.",
    "json_invalid": "O corpo da requisição não é um JSON válido.",
    "datetime_parsing": "Informe uma data válida.",
    "datetime_from_date_parsing": "Informe uma data válida.",
}


def _mensagem(erro: dict[str, Any]) -> str:
    tipo = erro.get("type", "")
    contexto = erro.get("ctx") or {}
    campo = str(erro.get("loc", [""])[-1])

    if tipo == "value_error" and "email" in str(erro.get("msg", "")).lower():
        return "Informe um e-mail válido."
    if tipo == "string_pattern_mismatch" and campo.startswith("periodo"):
        return "Informe o período no formato AAAA-MM."
    if tipo == "string_too_short":
        return f"Use no mínimo {contexto.get('min_length')} caracteres."
    if tipo == "string_too_long":
        return f"Use no máximo {contexto.get('max_length')} caracteres."
    if tipo == "too_short":
        return f"Informe pelo menos {contexto.get('min_length')} item(ns)."
    if tipo == "too_long":
        return f"Informe no máximo {contexto.get('max_length')} itens."
    if tipo == "greater_than":
        return f"Informe um valor maior que {contexto.get('gt')}."
    if tipo == "greater_than_equal":
        return f"Informe um valor a partir de {contexto.get('ge')}."
    if tipo == "less_than":
        return f"Informe um valor menor que {contexto.get('lt')}."
    if tipo == "less_than_equal":
        return f"Informe um valor de no máximo {contexto.get('le')}."
    return MENSAGENS_PADRAO.get(tipo, str(erro.get("msg", "Valor inválido.")))


async def tratar_erro_de_validacao(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Responde aos erros de validação com mensagens em português, sem devolver o
    valor recebido, que pode não ser serializável (como NaN ou Infinity).
    """
    detalhes = [
        {
            "type": erro.get("type"),
            "loc": list(erro.get("loc", [])),
            "msg": _mensagem(erro),
        }
        for erro in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detalhes})
