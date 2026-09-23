from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from src.schemas.enums import Perfil, StatusVinculo, StatusValidacao

# ==========================================
# Mixins Pydantic
# ==========================================
class TimestampSchemaMixin(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# ==========================================
# Schemas para Material
# ==========================================
class MaterialBase(BaseModel):
    categoria: str
    fator_emissaoipcc: float

class MaterialCreate(MaterialBase):
    pass

class MaterialUpdate(BaseModel):
    categoria: Optional[str] = None
    fator_emissaoipcc: Optional[float] = None

class MaterialResponse(MaterialBase, TimestampSchemaMixin):
    id: str

    model_config = ConfigDict(from_attributes=True)

# ==========================================
# Schemas para Prefeitura
# ==========================================
class PrefeituraBase(BaseModel):
    nome: str

class PrefeituraCreate(PrefeituraBase):
    pass

class PrefeituraResponse(PrefeituraBase, TimestampSchemaMixin):
    id: str

    model_config = ConfigDict(from_attributes=True)

# ==========================================
# Schemas para UsuarioAdmin (Prefeitura)
# ==========================================
class UsuarioAdminBase(BaseModel):
    nome: str
    email: EmailStr
    perfil: Perfil = Perfil.GESTOR

class UsuarioAdminCreate(UsuarioAdminBase):
    id_prefeitura: str
    senha: str = Field(..., min_length=6, description="Senha em texto plano que será hasheada no backend")

class UsuarioAdminUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[EmailStr] = None
    perfil: Optional[Perfil] = None

class UsuarioAdminResponse(UsuarioAdminBase, TimestampSchemaMixin):
    id: str
    id_prefeitura: str
    # Não incluímos a senha_hash na resposta por segurança

    model_config = ConfigDict(from_attributes=True)

# ==========================================
# Schemas para UsuarioEmpresa (Funcionários)
# ==========================================
class UsuarioEmpresaBase(BaseModel):
    nome: str
    email: EmailStr
    perfil: Perfil = Perfil.COMUM

class UsuarioEmpresaCreate(UsuarioEmpresaBase):
    id_empresa: str
    senha: str = Field(..., min_length=6, description="Senha em texto plano que será hasheada no backend")

class UsuarioEmpresaUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[EmailStr] = None
    perfil: Optional[Perfil] = None

class UsuarioEmpresaResponse(UsuarioEmpresaBase, TimestampSchemaMixin):
    id: str
    id_empresa: str
    # Não incluímos a senha_hash na resposta por segurança

    model_config = ConfigDict(from_attributes=True)

# ==========================================
# Schemas para Empresa
# ==========================================
class EmpresaBase(BaseModel):
    nome: str
    cnpj: str
    razao_social: str
    nome_fantasia: str
    telefone: str
    endereco: str

class EmpresaCreate(EmpresaBase):
    prefeitura_id: str
    senha: str = Field(..., min_length=6) 

class EmpresaUpdate(BaseModel):
    nome: Optional[str] = None
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    telefone: Optional[str] = None
    endereco: Optional[str] = None
    empresa_status: Optional[StatusVinculo] = None

class EmpresaResponse(EmpresaBase, TimestampSchemaMixin):
    id: str
    prefeitura_id: str
    empresa_status: StatusVinculo

    model_config = ConfigDict(from_attributes=True)

# ==========================================
# Schemas para Registro (Resíduos)
# ==========================================
class RegistroBase(BaseModel):
    periodo: str
    volume_total: float
    percentual_reciclado: float

class RegistroCreate(RegistroBase):
    empresa_id: str
    material_id: str

# Schema usado especificamente pelo Gestor da Prefeitura para validar/rejeitar
class RegistroValidacaoUpdate(BaseModel):
    status_validacao: StatusValidacao
    motivo_rejeicao: Optional[str] = None
    validador_id: str
    volume_validado: Optional[float] = None
    valorestimado: Optional[float] = None
    carbonoevitado: Optional[float] = None

class RegistroResponse(RegistroBase, TimestampSchemaMixin):
    id: str
    empresa_id: str
    material_id: str
    validador_id: Optional[str] = None
    status_validacao: StatusValidacao
    motivo_rejeicao: Optional[str] = None
    volume_validado: Optional[float] = None
    valorestimado: Optional[float] = None
    carbonoevitado: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)

# ==========================================
# Schemas Aninhados (Opcional - para joins)
# ==========================================
# Útil caso você queira retornar a Empresa junto com todos os seus Usuários
class EmpresaComUsuariosResponse(EmpresaResponse):
    usuarios: List[UsuarioEmpresaResponse] = []

    model_config = ConfigDict(from_attributes=True)