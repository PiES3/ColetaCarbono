from datetime import datetime

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from src.schemas.enums import Perfil, StatusValidacao, StatusVinculo
from src.schemas.validacao import (
    normalizar_cnpj,
    validar_endereco,
    validar_nome_fantasia,
    validar_percentual,
    validar_periodo,
    validar_razao_social,
    validar_telefone,
    validar_volume,
)


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


class ValidacaoDadosEmpresa(BaseModel):
    @field_validator("cnpj", check_fields=False)
    @classmethod
    def checar_cnpj(cls, valor: str | None) -> str | None:
        return None if valor is None else normalizar_cnpj(valor)

    @field_validator("razao_social", check_fields=False)
    @classmethod
    def checar_razao_social(cls, valor: str | None) -> str:
        return validar_razao_social(valor)

    @field_validator("nome_fantasia", check_fields=False)
    @classmethod
    def checar_nome_fantasia(cls, valor: str | None) -> str | None:
        return validar_nome_fantasia(valor)

    @field_validator("telefone", check_fields=False)
    @classmethod
    def checar_telefone(cls, valor: str | None) -> str | None:
        return validar_telefone(valor)

    @field_validator("endereco", check_fields=False)
    @classmethod
    def checar_endereco(cls, valor: str | None) -> str | None:
        return validar_endereco(valor)


class EmpresaCreate(ValidacaoDadosEmpresa, EmpresaBase):
    razao_social: str
    prefeitura_id: str
    senha: str


class EmpresaUpdate(ValidacaoDadosEmpresa):
    cnpj: str | None = None
    email: EmailStr | None = None
    razao_social: str | None = None
    nome_fantasia: str | None = None
    telefone: str | None = None
    endereco: str | None = None


class EmpresaResponse(TimestampSchemaMixin):
    id: str
    prefeitura_id: str
    cnpj: str
    email: EmailStr
    email_confirmado: bool = False
    email_pendente: str | None = None
    razao_social: str
    nome_fantasia: str | None = None
    telefone: str | None = None
    endereco: str | None = None
    empresa_status: StatusVinculo
    motivo_recusa: str | None = None

    model_config = ConfigDict(from_attributes=True)


class HistoricoCadastroResponse(BaseModel):
    id: str
    campo: str
    valor_anterior: str | None = None
    valor_novo: str | None = None
    autor_id: str
    autor_nome: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RegistroBase(BaseModel):
    periodo: str
    volume_total: float
    percentual_reciclado: float


class RegistroCreate(RegistroBase):
    material_id: str

    @field_validator("periodo")
    @classmethod
    def checar_periodo(cls, valor: str) -> str:
        return validar_periodo(valor)

    @field_validator("volume_total")
    @classmethod
    def checar_volume(cls, valor: float) -> float:
        return validar_volume(valor)

    @field_validator("percentual_reciclado")
    @classmethod
    def checar_percentual(cls, valor: float) -> float:
        return validar_percentual(valor)


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
    prefeitura_nome: str | None = None
    status_vinculo: StatusVinculo | None = None


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    nome: str
    user_type: str
    is_superuser: bool
    prefeitura_id: str | None = None
    prefeitura_nome: str | None = None
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
