from enum import StrEnum


class Perfil(StrEnum):
    ADMIN = "ADMIN"
    GESTOR = "GESTOR"
    COMUM = "COMUM"


class StatusVinculo(StrEnum):
    AGUARDANDO_VALIDACAO = "AGUARDANDO VALIDACAO"
    APROVADA = "APROVADA"
    RECUSADA = "RECUSADA"
    DESASSOCIADA = "DESASSOCIADA"


class StatusValidacao(StrEnum):
    PENDENTE = "PENDENTE"
    VALIDADO = "VALIDADO"
    RECUSADA = "RECUSADA"
