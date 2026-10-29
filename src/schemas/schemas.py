from datetime import datetime

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from src.schemas.enums import (
    AgrupamentoRelatorio,
    Perfil,
    StatusValidacao,
    StatusVinculo,
)
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
    categoria: str = Field(min_length=1, max_length=100)
    fator_emissaoipcc: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("categoria", mode="before")
    @classmethod
    def limpar_categoria(cls, valor: object) -> object:
        return valor.strip() if isinstance(valor, str) else valor


class MaterialUpdate(BaseModel):
    categoria: str | None = Field(default=None, min_length=1, max_length=100)
    fator_emissaoipcc: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("categoria", mode="before")
    @classmethod
    def limpar_categoria(cls, valor: object) -> object:
        return valor.strip() if isinstance(valor, str) else valor


class MaterialResponse(MaterialBase, TimestampSchemaMixin):
    id: str
    cor_conama: str = "#6C757D"

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
        min_length=8,
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
        min_length=8,
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
    desassociacao_solicitada: bool = False
    motivo_desassociacao: str | None = None
    data_solicitacao_desassociacao: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SolicitarDesassociacaoRequest(BaseModel):
    motivo: str | None = Field(
        default=None,
        max_length=500,
        validation_alias=AliasChoices("motivo", "motivo_desassociacao"),
    )

    @field_validator("motivo", mode="before")
    @classmethod
    def limpar_motivo(cls, valor: object) -> object:
        if isinstance(valor, str):
            texto = valor.strip()
            return texto or None
        return valor


class DecisaoDesassociacaoRequest(BaseModel):
    aprovar: bool
    motivo_resposta: str | None = Field(
        default=None,
        max_length=500,
        validation_alias=AliasChoices("motivo_resposta", "motivo"),
    )

    @field_validator("motivo_resposta", mode="before")
    @classmethod
    def limpar_resposta(cls, valor: object) -> object:
        if isinstance(valor, str):
            texto = valor.strip()
            return texto or None
        return valor


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
    empresa_id: str | None = None
    material_id: str
    client_id: str | None = Field(default=None, max_length=120)
    volume_validado: float | None = None

    @field_validator("periodo")
    @classmethod
    def checar_periodo(cls, valor: str) -> str:
        return validar_periodo(valor)

    @field_validator("volume_total")
    @classmethod
    def checar_volume(cls, valor: float) -> float:
        return validar_volume(valor)

    @field_validator("volume_validado")
    @classmethod
    def checar_volume_validado(cls, valor: float | None) -> float | None:
        return None if valor is None else validar_volume(valor)

    @field_validator("percentual_reciclado")
    @classmethod
    def checar_percentual(cls, valor: float) -> float:
        return validar_percentual(valor)


class RegistroGestorCreate(RegistroCreate):
    empresa_id: str

    @field_validator("periodo")
    @classmethod
    def checar_periodo(cls, valor: str) -> str:
        return validar_periodo(valor, permitir_futuro=True)


class RegistroValidacaoRequest(BaseModel):
    validador_id: str | None = None
    volume_validado: float | None = None

    @field_validator("volume_validado")
    @classmethod
    def checar_volume(cls, valor: float | None) -> float | None:
        return None if valor is None else validar_volume(valor)


class RegistroRejeicaoRequest(BaseModel):
    motivo_rejeicao: str | None = Field(
        default=None,
        validation_alias=AliasChoices("motivo_rejeicao", "motivo"),
        description="Motivo da rejeição do registro (obrigatório).",
    )
    validador_id: str | None = None


class RegistroValidacaoUpdate(BaseModel):
    status_validacao: StatusValidacao
    motivo_rejeicao: str | None = Field(
        default=None,
        validation_alias=AliasChoices("motivo_rejeicao", "motivo"),
    )
    validador_id: str | None = None
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
    client_id: str | None = None
    validador_id: str | None = None
    criado_por_gestor_id: str | None = None
    inserido_pela_prefeitura: bool = False
    origem: str = "EMPRESA"
    nome_gestor: str | None = None
    status_validacao: StatusValidacao
    status: StatusValidacao | None = None
    motivo_rejeicao: str | None = None
    motivo: str | None = None
    volume_validado: float | None = None
    valorestimado: float | None = None
    carbonoevitado: float | None = None
    data_validacao: datetime | None = None
    data_hora_validacao: datetime | None = None
    validador_nome: str | None = None
    nome_validador: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RegistroAcompanhamentoResponse(RegistroResponse):
    pass


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


class ResumoRegistrosResponse(BaseModel):
    total_registros: int = 0
    registros_pendentes: int = 0
    registros_validados: int = 0
    registros_rejeitados: int = 0
    volume_total_declarado: float = 0.0
    volume_total_validado: float = 0.0
    carbono_total_evitado: float = 0.0
    valor_total_estimado: float = 0.0
    percentual_medio_reciclado: float = 0.0


class EstatisticaMaterialItem(BaseModel):
    material_id: str
    categoria: str
    cor_conama: str = "#6C757D"
    total_registros: int = 0
    volume_declarado: float = 0.0
    volume_validado: float = 0.0
    carbono_evitado: float = 0.0
    valor_estimado: float = 0.0


class EstatisticaPeriodoItem(BaseModel):
    periodo: str
    total_registros: int = 0
    registros_validados: int = 0
    registros_pendentes: int = 0
    registros_rejeitados: int = 0
    volume_declarado: float = 0.0
    volume_validado: float = 0.0
    carbono_evitado: float = 0.0
    valor_estimado: float = 0.0


class EstatisticaEmpresaItem(BaseModel):
    empresa_id: str
    razao_social: str
    nome_fantasia: str | None = None
    cnpj: str
    total_registros: int = 0
    registros_validados: int = 0
    registros_pendentes: int = 0
    registros_rejeitados: int = 0
    volume_declarado: float = 0.0
    volume_validado: float = 0.0
    carbono_evitado: float = 0.0
    valor_estimado: float = 0.0


class DashboardResumoResponse(BaseModel):
    escopo: str
    empresas_por_status: dict[str, int] | None = None
    total_empresas: int | None = None
    registros_por_status: dict[str, int]
    resumo_registros: ResumoRegistrosResponse
    por_material: list[EstatisticaMaterialItem] = []
    por_periodo: list[EstatisticaPeriodoItem] = []
    ranking_empresas: list[EstatisticaEmpresaItem] = []


class SincronizacaoLoteRequest(BaseModel):
    registros: list[RegistroCreate] = Field(min_length=1, max_length=500)


class ErroSincronizacaoItem(BaseModel):
    indice: int
    client_id: str | None = None
    erro: str


class SincronizacaoLoteResponse(BaseModel):
    total_recebidos: int
    total_criados: int
    total_duplicados: int
    total_erros: int
    registros: list[RegistroResponse] = []
    erros: list[ErroSincronizacaoItem] = []


class EvolucaoDiariaItem(BaseModel):
    data: str
    total_registros: int = 0
    registros_validados: int = 0
    volume_declarado: float = 0.0
    volume_validado: float = 0.0
    carbono_evitado: float = 0.0
    valor_estimado: float = 0.0


class EvolucaoTemporalResponse(BaseModel):
    dias: int
    data_inicio: str
    data_fim: str
    volume_periodo_atual: float = 0.0
    volume_periodo_anterior: float = 0.0
    variacao_volume_pct: float | None = None
    carbono_periodo_atual: float = 0.0
    carbono_periodo_anterior: float = 0.0
    variacao_carbono_pct: float | None = None
    serie_diaria: list[EvolucaoDiariaItem] = []


class GrupoRelatorioItem(BaseModel):
    chave_periodo: str
    rotulo: str
    total_registros: int = 0
    registros_validados: int = 0
    registros_pendentes: int = 0
    registros_rejeitados: int = 0
    volume_declarado: float = 0.0
    volume_validado: float = 0.0
    carbono_evitado: float = 0.0
    valor_estimado: float = 0.0
    por_material: list[EstatisticaMaterialItem] = []


class RelatorioConsolidadoResponse(BaseModel):
    escopo: str
    entidade_nome: str
    municipio_nome: str | None = None
    agrupamento: AgrupamentoRelatorio
    gerado_em: datetime
    resumo: ResumoRegistrosResponse
    por_material: list[EstatisticaMaterialItem] = []
    grupos: list[GrupoRelatorioItem] = []


class HealthLiveResponse(BaseModel):
    status: str = "ok"
    servico: str = "ColetaCarbono"
    versao: str = "0.1.0"
    timestamp: datetime
    uptime_segundos: float


class ComponenteBancoSaude(BaseModel):
    status: str
    dialeto: str
    conectado: bool
    schema_integro: bool
    latencia_ms: float
    detalhe: str | None = None


class HealthStatusResponse(HealthLiveResponse):
    pronto: bool
    banco_dados: ComponenteBancoSaude
