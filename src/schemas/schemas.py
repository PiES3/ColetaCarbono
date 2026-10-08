import re
from datetime import datetime

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)
from pydantic_core import PydanticCustomError

from src.schemas.enums import Perfil, StatusValidacao, StatusVinculo

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


def exigir_razao_social(valor: str | None) -> str:
    texto = (valor or "").strip()
    if not texto:
        raise PydanticCustomError("razao_social_obrigatoria", "Informe a razão social.")
    return texto


class TimestampSchemaMixin(BaseModel):
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaterialBase(BaseModel):
    categoria: str
    fator_emissaoipcc: float


class MaterialCreate(MaterialBase):
    pass


class MaterialUpdate(BaseModel):
    categoria: str | None = None
    fator_emissaoipcc: float | None = None


class MaterialResponse(MaterialBase, TimestampSchemaMixin):
    id: str

    model_config = ConfigDict(from_attributes=True)


class PrefeituraBase(BaseModel):
    nome: str


class PrefeituraCreate(PrefeituraBase):
    pass


class PrefeituraResponse(PrefeituraBase, TimestampSchemaMixin):
    id: str

    model_config = ConfigDict(from_attributes=True)


class UsuarioAdminBase(BaseModel):
    nome: str
    email: EmailStr
    perfil: Perfil = Perfil.GESTOR


class UsuarioAdminCreate(UsuarioAdminBase):
    id_prefeitura: str
    senha: str = Field(
        ...,
        min_length=6,
        description="Senha em texto plano que será hasheada no backend",
    )


class UsuarioAdminUpdate(BaseModel):
    nome: str | None = None
    email: EmailStr | None = None
    perfil: Perfil | None = None


class UsuarioAdminResponse(UsuarioAdminBase, TimestampSchemaMixin):
    id: str
    id_prefeitura: str

    model_config = ConfigDict(from_attributes=True)


class UsuarioEmpresaBase(BaseModel):
    nome: str
    email: EmailStr
    perfil: Perfil = Perfil.COMUM


class UsuarioEmpresaCreate(UsuarioEmpresaBase):
    id_empresa: str
    senha: str = Field(
        ...,
        min_length=6,
        description="Senha em texto plano que será hasheada no backend",
    )


class UsuarioEmpresaUpdate(BaseModel):
    nome: str | None = None
    email: EmailStr | None = None
    perfil: Perfil | None = None


class UsuarioEmpresaResponse(UsuarioEmpresaBase, TimestampSchemaMixin):
    id: str
    id_empresa: str

    model_config = ConfigDict(from_attributes=True)


class EmpresaBase(BaseModel):
    cnpj: str
    email: EmailStr
    razao_social: str | None = None
    nome_fantasia: str | None = None
    telefone: str | None = None
    endereco: str | None = None


class EmpresaCreate(EmpresaBase):
    razao_social: str
    prefeitura_id: str
    senha: str = Field(..., min_length=6)

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj(cls, valor: str) -> str:
        return normalizar_cnpj(valor)

    @field_validator("razao_social")
    @classmethod
    def validar_razao_social(cls, valor: str) -> str:
        return exigir_razao_social(valor)


class EmpresaUpdate(BaseModel):
    email: EmailStr | None = None
    razao_social: str | None = None
    nome_fantasia: str | None = None
    telefone: str | None = None
    endereco: str | None = None
    empresa_status: StatusVinculo | None = None


class EmpresaResponse(TimestampSchemaMixin):
    id: str
    prefeitura_id: str
    cnpj: str
    email: EmailStr
    razao_social: str
    nome_fantasia: str | None = None
    telefone: str | None = None
    endereco: str | None = None
    empresa_status: StatusVinculo

    model_config = ConfigDict(from_attributes=True)


class RegistroBase(BaseModel):
    periodo: str
    volume_total: float
    percentual_reciclado: float


class RegistroCreate(RegistroBase):
    material_id: str


class RegistroValidacaoUpdate(BaseModel):
    status_validacao: StatusValidacao
    motivo_rejeicao: str | None = None
    validador_id: str
    volume_validado: float | None = None
    valorestimado: float | None = None
    carbonoevitado: float | None = None


class RegistroResponse(RegistroBase, TimestampSchemaMixin):
    volume_total: float = Field(
        validation_alias=AliasChoices("volume_total_original", "volume_total")
    )
    id: str
    empresa_id: str
    material_id: str
    validador_id: str | None = None
    status_validacao: StatusValidacao
    motivo_rejeicao: str | None = None
    volume_validado: float | None = None
    valorestimado: float | None = None
    carbonoevitado: float | None = None

    model_config = ConfigDict(from_attributes=True)


class EmpresaComUsuariosResponse(EmpresaResponse):
    usuarios: list[UsuarioEmpresaResponse] = []

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_type: str
    user_id: str
    email: str
    nome: str
    prefeitura_id: str | None = None
    status_vinculo: StatusVinculo | None = None


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    nome: str
    user_type: str
    is_superuser: bool
    prefeitura_id: str | None = None
    status_vinculo: StatusVinculo | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ConfirmacaoEmailRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    nova_senha: str


class MessageResponse(BaseModel):
    message: str
