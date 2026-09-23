from enum import Enum

class Perfil(str, Enum):
    ADMIN = "ADMIN"
    GESTOR = "GESTOR"
    COMUM = "COMUM"


class StatusVinculo(str, Enum):

    AGUARDANDO_VALIDACAO = "AGUARDANDO VALIDACAO"
    APROVADA = "APROVADA"
    RECUSADA = "RECUSADA"
    DESASSOCIADA = "DESASSOCIADA"

class StatusValidacao(str, Enum):

    PENDENTE = "PENDENTE"
    VALIDADO = "VALIDADO"
    RECUSADA = "RECUSADA"