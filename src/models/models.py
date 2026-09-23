from __future__ import annotations
from typing import List, Optional
from datetime import datetime
from sqlalchemy import String, Float, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.base import Base, TimestampMixin, gen_uuid
from src.schemas.enums import Perfil, StatusVinculo, StatusValidacao

class Prefeitura(Base, TimestampMixin):
    __tablename__ = "prefeituras"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    nome: Mapped[str] = mapped_column(String, nullable=False)

    empresas: Mapped[List["Empresa"]] = relationship(
        back_populates="prefeitura", cascade="all, delete-orphan"
    )
    administradores: Mapped[List["UsuarioAdmin"]] = relationship(
        back_populates="prefeitura", cascade="all, delete-orphan"
    )

class Empresa(Base, TimestampMixin):
    __tablename__ = "empresas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    prefeitura_id: Mapped[str] = mapped_column(ForeignKey("prefeituras.id"))
    
    cnpj: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    razao_social: Mapped[str] = mapped_column(String, nullable=False)
    nome_fantasia: Mapped[str] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    telefone: Mapped[str] = mapped_column(String, nullable=True)
    endereco: Mapped[str] = mapped_column(String, nullable=True)
    pwd_hash: Mapped[str] = mapped_column(String, nullable=False)
    
    empresa_status: Mapped[StatusVinculo] = mapped_column(
        SQLEnum(StatusVinculo), default=StatusVinculo.AGUARDANDO_VALIDACAO
    )
    motivo_recusa: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    token_confirmacao_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    token_expiracao: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    prefeitura: Mapped["Prefeitura"] = relationship(back_populates="empresas")
    usuarios: Mapped[List["UsuarioEmpresa"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    registros: Mapped[List["Registro"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )

class Material(Base, TimestampMixin):
    __tablename__ = "materiais"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    categoria: Mapped[str] = mapped_column(String, nullable=False)
    fator_emissaoipcc: Mapped[float] = mapped_column(Float, nullable=False)

    registros: Mapped[List["Registro"]] = relationship(back_populates="material")

class Registro(Base, TimestampMixin):
    __tablename__ = "registros"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    empresa_id: Mapped[str] = mapped_column(ForeignKey("empresas.id"))
    material_id: Mapped[str] = mapped_column(ForeignKey("materiais.id"))
    
    validador_id: Mapped[Optional[str]] = mapped_column(ForeignKey("usuarios_admin.id"), nullable=True) 
    criado_por_gestor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("usuarios_admin.id"), nullable=True) 
    
    periodo: Mapped[str] = mapped_column(String, nullable=False)
    volume_total_original: Mapped[float] = mapped_column(Float, nullable=False)
    percentual_reciclado: Mapped[float] = mapped_column(Float, nullable=False)
    
    status_validacao: Mapped[StatusValidacao] = mapped_column(
        SQLEnum(StatusValidacao), default=StatusValidacao.PENDENTE
    )
    motivo_rejeicao: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    volume_validado: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valorestimado: Mapped[Optional[float]] = mapped_column(Float, nullable=True) 
    carbonoevitado: Mapped[Optional[float]] = mapped_column(Float, nullable=True) 

    empresa: Mapped["Empresa"] = relationship(back_populates="registros")
    material: Mapped["Material"] = relationship(back_populates="registros")
    
    # Necessário especificar as chaves estrangeiras para evitar conflitos no SQLAlchemy
    validador: Mapped[Optional["UsuarioAdmin"]] = relationship(foreign_keys=[validador_id])
    criador_gestor: Mapped[Optional["UsuarioAdmin"]] = relationship(foreign_keys=[criado_por_gestor_id])

class UsuarioAdmin(Base, TimestampMixin):
    __tablename__ = "usuarios_admin"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    id_prefeitura: Mapped[str] = mapped_column(ForeignKey("prefeituras.id"))
    
    nome: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String, nullable=False)
    perfil: Mapped[Perfil] = mapped_column(SQLEnum(Perfil), default=Perfil.GESTOR)

    prefeitura: Mapped["Prefeitura"] = relationship(back_populates="administradores")

class UsuarioEmpresa(Base, TimestampMixin):
    __tablename__ = "usuarios_empresa"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    id_empresa: Mapped[str] = mapped_column(ForeignKey("empresas.id"))
    
    nome: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String, nullable=False)
    perfil: Mapped[Perfil] = mapped_column(SQLEnum(Perfil), default=Perfil.COMUM)

    empresa: Mapped["Empresa"] = relationship(back_populates="usuarios")