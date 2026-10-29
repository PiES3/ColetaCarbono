from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Query as ConsultaSQL
from sqlalchemy.orm import Session

from src.core.security import require_empresa
from src.models.models import Empresa, Material, Registro
from src.schemas.enums import StatusValidacao, StatusVinculo
from src.schemas.schemas import (
    DashboardResumoResponse,
    EstatisticaEmpresaItem,
    EstatisticaMaterialItem,
    EstatisticaPeriodoItem,
    ResumoRegistrosResponse,
)

STATUS_REGISTRO_PADRAO = (
    StatusValidacao.PENDENTE.value,
    StatusValidacao.VALIDADO.value,
    StatusValidacao.REJEITADO.value,
)

STATUS_EMPRESA_PADRAO = tuple(s.value for s in StatusVinculo)


def _arredondar(valor: float | None, casas: int = 2) -> float:
    return round(float(valor or 0.0), casas)


class EstatisticasService:
    def _filtrar_escopo_registros(
        self,
        query: ConsultaSQL,
        usuario: dict[str, Any],
        empresa_id: str | None = None,
        periodo: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
        material_id: str | None = None,
    ) -> ConsultaSQL:
        if usuario["user_type"] == "PREFEITURA":
            query = query.join(Empresa, Registro.empresa_id == Empresa.id).filter(
                Empresa.prefeitura_id == usuario["prefeitura_id"]
            )
            if empresa_id:
                query = query.filter(Registro.empresa_id == empresa_id)
        else:
            require_empresa(usuario)
            query = query.filter(Registro.empresa_id == usuario["empresa_id"])

        if material_id:
            query = query.filter(Registro.material_id == material_id)
        if periodo:
            query = query.filter(Registro.periodo == periodo)
        if periodo_inicio:
            query = query.filter(Registro.periodo >= periodo_inicio)
        if periodo_fim:
            query = query.filter(Registro.periodo <= periodo_fim)

        return query

    def empresas_por_status(self, db: Session, prefeitura_id: str) -> dict[str, int]:
        contagens = dict.fromkeys(STATUS_EMPRESA_PADRAO, 0)
        resultados = (
            db.query(Empresa.empresa_status, func.count(Empresa.id))
            .filter(Empresa.prefeitura_id == prefeitura_id)
            .group_by(Empresa.empresa_status)
            .all()
        )
        for status_vinculo, total in resultados:
            contagens[str(status_vinculo)] = int(total)
        return contagens

    def registros_por_status(
        self,
        db: Session,
        usuario: dict[str, Any],
        empresa_id: str | None = None,
        periodo: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
        material_id: str | None = None,
    ) -> dict[str, int]:
        contagens = dict.fromkeys(STATUS_REGISTRO_PADRAO, 0)
        query = self._filtrar_escopo_registros(
            db.query(Registro.status_validacao, func.count(Registro.id)),
            usuario=usuario,
            empresa_id=empresa_id,
            periodo=periodo,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
            material_id=material_id,
        )
        for status_reg, total in query.group_by(Registro.status_validacao).all():
            chave = str(status_reg)
            if chave == "RECUSADA":
                chave = StatusValidacao.REJEITADO.value
            contagens[chave] = contagens.get(chave, 0) + int(total)
        return contagens

    def resumo_registros(
        self,
        db: Session,
        usuario: dict[str, Any],
        empresa_id: str | None = None,
        periodo: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
        material_id: str | None = None,
    ) -> ResumoRegistrosResponse:
        eh_validado = Registro.status_validacao == StatusValidacao.VALIDADO
        eh_pendente = Registro.status_validacao == StatusValidacao.PENDENTE
        eh_rejeitado = Registro.status_validacao.in_(
            [StatusValidacao.REJEITADO, "RECUSADA"]
        )

        query = self._filtrar_escopo_registros(
            db.query(
                func.count(Registro.id),
                func.coalesce(func.sum(case((eh_pendente, 1), else_=0)), 0),
                func.coalesce(func.sum(case((eh_validado, 1), else_=0)), 0),
                func.coalesce(func.sum(case((eh_rejeitado, 1), else_=0)), 0),
                func.coalesce(func.sum(Registro.volume_total_original), 0.0),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.volume_validado), else_=0.0)),
                    0.0,
                ),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.carbonoevitado), else_=0.0)),
                    0.0,
                ),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.valorestimado), else_=0.0)),
                    0.0,
                ),
                func.coalesce(func.avg(Registro.percentual_reciclado), 0.0),
            ),
            usuario=usuario,
            empresa_id=empresa_id,
            periodo=periodo,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
            material_id=material_id,
        )
        (
            total,
            pendentes,
            validados,
            rejeitados,
            vol_declarado,
            vol_validado,
            carbono,
            valor,
            perc_medio,
        ) = query.one()

        return ResumoRegistrosResponse(
            total_registros=int(total or 0),
            registros_pendentes=int(pendentes or 0),
            registros_validados=int(validados or 0),
            registros_rejeitados=int(rejeitados or 0),
            volume_total_declarado=_arredondar(vol_declarado),
            volume_total_validado=_arredondar(vol_validado),
            carbono_total_evitado=_arredondar(carbono, 4),
            valor_total_estimado=_arredondar(valor),
            percentual_medio_reciclado=_arredondar(perc_medio),
        )

    def por_material(
        self,
        db: Session,
        usuario: dict[str, Any],
        empresa_id: str | None = None,
        periodo: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
    ) -> list[EstatisticaMaterialItem]:
        eh_validado = Registro.status_validacao == StatusValidacao.VALIDADO
        query = self._filtrar_escopo_registros(
            db.query(
                Material.id,
                Material.categoria,
                func.count(Registro.id),
                func.coalesce(func.sum(Registro.volume_total_original), 0.0),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.volume_validado), else_=0.0)),
                    0.0,
                ),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.carbonoevitado), else_=0.0)),
                    0.0,
                ),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.valorestimado), else_=0.0)),
                    0.0,
                ),
            ).join(Material, Registro.material_id == Material.id),
            usuario=usuario,
            empresa_id=empresa_id,
            periodo=periodo,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
        )
        linhas = (
            query.group_by(Material.id, Material.categoria)
            .order_by(Material.categoria.asc())
            .all()
        )
        return [
            EstatisticaMaterialItem(
                material_id=mat_id,
                categoria=categoria,
                total_registros=int(total or 0),
                volume_declarado=_arredondar(vol_decl),
                volume_validado=_arredondar(vol_val),
                carbono_evitado=_arredondar(carbono, 4),
                valor_estimado=_arredondar(valor),
            )
            for mat_id, categoria, total, vol_decl, vol_val, carbono, valor in linhas
        ]

    def por_periodo(
        self,
        db: Session,
        usuario: dict[str, Any],
        empresa_id: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
        material_id: str | None = None,
    ) -> list[EstatisticaPeriodoItem]:
        eh_validado = Registro.status_validacao == StatusValidacao.VALIDADO
        eh_pendente = Registro.status_validacao == StatusValidacao.PENDENTE
        eh_rejeitado = Registro.status_validacao.in_(
            [StatusValidacao.REJEITADO, "RECUSADA"]
        )
        query = self._filtrar_escopo_registros(
            db.query(
                Registro.periodo,
                func.count(Registro.id),
                func.coalesce(func.sum(case((eh_validado, 1), else_=0)), 0),
                func.coalesce(func.sum(case((eh_pendente, 1), else_=0)), 0),
                func.coalesce(func.sum(case((eh_rejeitado, 1), else_=0)), 0),
                func.coalesce(func.sum(Registro.volume_total_original), 0.0),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.volume_validado), else_=0.0)),
                    0.0,
                ),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.carbonoevitado), else_=0.0)),
                    0.0,
                ),
                func.coalesce(
                    func.sum(case((eh_validado, Registro.valorestimado), else_=0.0)),
                    0.0,
                ),
            ),
            usuario=usuario,
            empresa_id=empresa_id,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
            material_id=material_id,
        )
        linhas = query.group_by(Registro.periodo).order_by(Registro.periodo.asc()).all()
        return [
            EstatisticaPeriodoItem(
                periodo=per,
                total_registros=int(total or 0),
                registros_validados=int(validados or 0),
                registros_pendentes=int(pendentes or 0),
                registros_rejeitados=int(rejeitados or 0),
                volume_declarado=_arredondar(vol_decl),
                volume_validado=_arredondar(vol_val),
                carbono_evitado=_arredondar(carbono, 4),
                valor_estimado=_arredondar(valor),
            )
            for (
                per,
                total,
                validados,
                pendentes,
                rejeitados,
                vol_decl,
                vol_val,
                carbono,
                valor,
            ) in linhas
        ]

    def ranking_empresas(
        self,
        db: Session,
        prefeitura_id: str,
        periodo: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
        material_id: str | None = None,
        limit: int = 10,
    ) -> list[EstatisticaEmpresaItem]:
        eh_validado = Registro.status_validacao == StatusValidacao.VALIDADO
        eh_pendente = Registro.status_validacao == StatusValidacao.PENDENTE
        eh_rejeitado = Registro.status_validacao.in_(
            [StatusValidacao.REJEITADO, "RECUSADA"]
        )
        carbono_soma = func.coalesce(
            func.sum(case((eh_validado, Registro.carbonoevitado), else_=0.0)),
            0.0,
        )
        vol_val_soma = func.coalesce(
            func.sum(case((eh_validado, Registro.volume_validado), else_=0.0)),
            0.0,
        )

        query = (
            db.query(
                Empresa.id,
                Empresa.razao_social,
                Empresa.nome_fantasia,
                Empresa.cnpj,
                func.count(Registro.id),
                func.coalesce(func.sum(case((eh_validado, 1), else_=0)), 0),
                func.coalesce(func.sum(case((eh_pendente, 1), else_=0)), 0),
                func.coalesce(func.sum(case((eh_rejeitado, 1), else_=0)), 0),
                func.coalesce(func.sum(Registro.volume_total_original), 0.0),
                vol_val_soma,
                carbono_soma,
                func.coalesce(
                    func.sum(case((eh_validado, Registro.valorestimado), else_=0.0)),
                    0.0,
                ),
            )
            .join(Registro, Registro.empresa_id == Empresa.id)
            .filter(Empresa.prefeitura_id == prefeitura_id)
        )
        if material_id:
            query = query.filter(Registro.material_id == material_id)
        if periodo:
            query = query.filter(Registro.periodo == periodo)
        if periodo_inicio:
            query = query.filter(Registro.periodo >= periodo_inicio)
        if periodo_fim:
            query = query.filter(Registro.periodo <= periodo_fim)

        linhas = (
            query.group_by(
                Empresa.id,
                Empresa.razao_social,
                Empresa.nome_fantasia,
                Empresa.cnpj,
            )
            .order_by(carbono_soma.desc(), vol_val_soma.desc())
            .limit(limit)
            .all()
        )
        return [
            EstatisticaEmpresaItem(
                empresa_id=emp_id,
                razao_social=razao,
                nome_fantasia=fantasia,
                cnpj=cnpj,
                total_registros=int(total or 0),
                registros_validados=int(validados or 0),
                registros_pendentes=int(pendentes or 0),
                registros_rejeitados=int(rejeitados or 0),
                volume_declarado=_arredondar(vol_decl),
                volume_validado=_arredondar(vol_val),
                carbono_evitado=_arredondar(carbono, 4),
                valor_estimado=_arredondar(valor),
            )
            for (
                emp_id,
                razao,
                fantasia,
                cnpj,
                total,
                validados,
                pendentes,
                rejeitados,
                vol_decl,
                vol_val,
                carbono,
                valor,
            ) in linhas
        ]

    def dashboard_completo(
        self,
        db: Session,
        usuario: dict[str, Any],
        empresa_id: str | None = None,
        periodo: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
        material_id: str | None = None,
    ) -> DashboardResumoResponse:
        eh_prefeitura = usuario["user_type"] == "PREFEITURA"
        empresas_status: dict[str, int] | None = None
        total_empresas: int | None = None
        ranking: list[EstatisticaEmpresaItem] = []

        if eh_prefeitura:
            prefeitura_id = usuario["prefeitura_id"]
            empresas_status = self.empresas_por_status(db, prefeitura_id)
            total_empresas = sum(empresas_status.values())
            ranking = self.ranking_empresas(
                db=db,
                prefeitura_id=prefeitura_id,
                periodo=periodo,
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
                material_id=material_id,
            )

        resumo = self.resumo_registros(
            db=db,
            usuario=usuario,
            empresa_id=empresa_id,
            periodo=periodo,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
            material_id=material_id,
        )
        reg_status = {
            StatusValidacao.PENDENTE.value: resumo.registros_pendentes,
            StatusValidacao.VALIDADO.value: resumo.registros_validados,
            StatusValidacao.REJEITADO.value: resumo.registros_rejeitados,
        }

        return DashboardResumoResponse(
            escopo="PREFEITURA" if eh_prefeitura else "EMPRESA",
            empresas_por_status=empresas_status,
            total_empresas=total_empresas,
            registros_por_status=reg_status,
            resumo_registros=resumo,
            por_material=self.por_material(
                db=db,
                usuario=usuario,
                empresa_id=empresa_id,
                periodo=periodo,
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
            ),
            por_periodo=self.por_periodo(
                db=db,
                usuario=usuario,
                empresa_id=empresa_id,
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
                material_id=material_id,
            ),
            ranking_empresas=ranking,
        )


estatisticas_service = EstatisticasService()
