from __future__ import annotations

import unicodedata
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.base import Base, TimestampMixin, gen_uuid
from src.schemas.enums import Perfil, StatusValidacao, StatusVinculo

CORES_CONAMA_275: tuple[tuple[tuple[str, ...], str], ...] = (
    (("papel", "papelao", "celulose"), "#0057B8"),  # Azul
    (("plastico", "pet", "pvc", "pead", "polietileno"), "#D62828"),  # Vermelho
    (("vidro",), "#2A9D49"),  # Verde
    (("metal", "aluminio", "aco", "ferro", "lata", "cobre"), "#F4B400"),  # Amarelo
    (("madeira",), "#212529"),  # Preto
    (("organico", "compost"), "#6D4C41"),  # Marrom
    (("perigoso", "pilha", "bateria"), "#F77F00"),  # Laranja
    (("hospitalar", "saude"), "#EAEAEA"),  # Branco
    (("radioativo",), "#7B2CBF"),  # Roxo
)


def cor_conama_por_categoria(categoria: str) -> str:
    """Retorna o código hexadecimal CONAMA 275 correspondente à categoria."""
    normalizada = (
        unicodedata.normalize("NFKD", categoria or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    for termos, cor in CORES_CONAMA_275:
        if any(termo in normalizada for termo in termos):
            return cor
    return "#6C757D"  # Cinza (resíduo geral / não reciclável)


class Prefeitura(Base, TimestampMixin):
    __tablename__ = "prefeituras"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    nome: Mapped[str] = mapped_column(String, nullable=False)

    empresas: Mapped[list[Empresa]] = relationship(
        back_populates="prefeitura", cascade="all, delete-orphan"
    )
    administradores: Mapped[list[UsuarioAdmin]] = relationship(
        back_populates="prefeitura", cascade="all, delete-orphan"
    )


class Empresa(Base, TimestampMixin):
    __tablename__ = "empresas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    prefeitura_id: Mapped[str] = mapped_column(
        ForeignKey("prefeituras.id"), nullable=False, index=True
    )

    cnpj: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    razao_social: Mapped[str] = mapped_column(String, nullable=False)
    nome_fantasia: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    telefone: Mapped[str | None] = mapped_column(String, nullable=True)
    endereco: Mapped[str | None] = mapped_column(String, nullable=True)
    pwd_hash: Mapped[str] = mapped_column(String, nullable=False)

    empresa_status: Mapped[StatusVinculo] = mapped_column(
        SQLEnum(StatusVinculo), default=StatusVinculo.AGUARDANDO_VALIDACAO
    )
    motivo_recusa: Mapped[str | None] = mapped_column(String, nullable=True)
    desassociacao_solicitada: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo_desassociacao: Mapped[str | None] = mapped_column(String, nullable=True)
    data_solicitacao_desassociacao: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    email_confirmado: Mapped[bool] = mapped_column(Boolean, default=False)
    email_pendente: Mapped[str | None] = mapped_column(String, nullable=True)
    token_confirmacao_email: Mapped[str | None] = mapped_column(String, nullable=True)
    token_expiracao: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    prefeitura: Mapped[Prefeitura] = relationship(back_populates="empresas")
    usuarios: Mapped[list[UsuarioEmpresa]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    registros: Mapped[list[Registro]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    historico: Mapped[list[HistoricoCadastro]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )


class HistoricoCadastro(Base, TimestampMixin):
    __tablename__ = "historico_cadastro"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    empresa_id: Mapped[str] = mapped_column(ForeignKey("empresas.id"), index=True)
    autor_id: Mapped[str] = mapped_column(String, nullable=False)
    autor_nome: Mapped[str] = mapped_column(String, nullable=False)
    campo: Mapped[str] = mapped_column(String, nullable=False)
    valor_anterior: Mapped[str | None] = mapped_column(String, nullable=True)
    valor_novo: Mapped[str | None] = mapped_column(String, nullable=True)

    empresa: Mapped[Empresa] = relationship(back_populates="historico")


class Material(Base, TimestampMixin):
    __tablename__ = "materiais"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    categoria: Mapped[str] = mapped_column(String, nullable=False)
    fator_emissaoipcc: Mapped[float] = mapped_column(Float, nullable=False)

    registros: Mapped[list[Registro]] = relationship(back_populates="material")

    @property
    def cor_conama(self) -> str:
        return cor_conama_por_categoria(self.categoria)


class Registro(Base, TimestampMixin):
    __tablename__ = "registros"
    __table_args__ = (
        UniqueConstraint("empresa_id", "client_id", name="uq_registros_empresa_client"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    empresa_id: Mapped[str] = mapped_column(
        ForeignKey("empresas.id"), nullable=False, index=True
    )
    material_id: Mapped[str] = mapped_column(ForeignKey("materiais.id"), nullable=False)
    client_id: Mapped[str | None] = mapped_column(String, nullable=True)

    validador_id: Mapped[str | None] = mapped_column(
        ForeignKey("usuarios_admin.id"), nullable=True
    )
    criado_por_gestor_id: Mapped[str | None] = mapped_column(
        ForeignKey("usuarios_admin.id"), nullable=True
    )

    periodo: Mapped[str] = mapped_column(String, nullable=False)
    volume_total_original: Mapped[float] = mapped_column(Float, nullable=False)
    percentual_reciclado: Mapped[float] = mapped_column(Float, nullable=False)

    status_validacao: Mapped[StatusValidacao] = mapped_column(
        SQLEnum(StatusValidacao), default=StatusValidacao.PENDENTE
    )
    motivo_rejeicao: Mapped[str | None] = mapped_column(String, nullable=True)

    volume_validado: Mapped[float | None] = mapped_column(Float, nullable=True)
    valorestimado: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbonoevitado: Mapped[float | None] = mapped_column(Float, nullable=True)
    _data_validacao: Mapped[datetime | None] = mapped_column(
        "data_validacao", DateTime, nullable=True
    )

    empresa: Mapped[Empresa] = relationship(back_populates="registros")
    material: Mapped[Material] = relationship(back_populates="registros")

    validador: Mapped[UsuarioAdmin | None] = relationship(foreign_keys=[validador_id])
    criador_gestor: Mapped[UsuarioAdmin | None] = relationship(
        foreign_keys=[criado_por_gestor_id]
    )

    @property
    def inserido_pela_prefeitura(self) -> bool:
        return self.criado_por_gestor_id is not None

    @property
    def origem(self) -> str:
        return "PREFEITURA" if self.criado_por_gestor_id else "EMPRESA"

    @property
    def nome_gestor(self) -> str | None:
        return self.criador_gestor.nome if self.criador_gestor else None

    @property
    def status(self) -> StatusValidacao:
        return self.status_validacao

    @property
    def motivo(self) -> str | None:
        return self.motivo_rejeicao

    @property
    def data_validacao(self) -> datetime | None:
        if self.status_validacao == StatusValidacao.VALIDADO:
            return self._data_validacao or self.updated_at
        return None

    @data_validacao.setter
    def data_validacao(self, value: datetime | None) -> None:
        self._data_validacao = value

    @property
    def data_hora_validacao(self) -> datetime | None:
        return self.data_validacao

    @property
    def nome_validador(self) -> str | None:
        if self.status_validacao == StatusValidacao.VALIDADO and self.validador:
            return self.validador.nome
        return None

    @property
    def validador_nome(self) -> str | None:
        return self.nome_validador


class UsuarioAdmin(Base, TimestampMixin):
    __tablename__ = "usuarios_admin"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    id_prefeitura: Mapped[str] = mapped_column(
        ForeignKey("prefeituras.id"), nullable=False
    )

    nome: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String, nullable=False)
    perfil: Mapped[Perfil] = mapped_column(SQLEnum(Perfil), default=Perfil.GESTOR)

    prefeitura: Mapped[Prefeitura] = relationship(back_populates="administradores")


class UsuarioEmpresa(Base, TimestampMixin):
    __tablename__ = "usuarios_empresa"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    id_empresa: Mapped[str] = mapped_column(ForeignKey("empresas.id"), nullable=False)

    nome: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String, nullable=False)
    perfil: Mapped[Perfil] = mapped_column(SQLEnum(Perfil), default=Perfil.COMUM)

    empresa: Mapped[Empresa] = relationship(back_populates="usuarios")


class TokenRedefinicaoSenha(Base, TimestampMixin):
    __tablename__ = "tokens_redefinicao_senha"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    token: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    expiracao: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    utilizado: Mapped[bool] = mapped_column(Boolean, default=False)
