from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Query as ConsultaSQL
from sqlalchemy.orm import Session, joinedload

from src.core.security import require_empresa
from src.models.models import Empresa, Material, Registro, cor_conama_por_categoria
from src.schemas.enums import AgrupamentoRelatorio, StatusValidacao, StatusVinculo
from src.schemas.schemas import (
    DashboardResumoResponse,
    EstatisticaEmpresaItem,
    EstatisticaMaterialItem,
    EstatisticaPeriodoItem,
    EvolucaoDiariaItem,
    EvolucaoTemporalResponse,
    GrupoRelatorioItem,
    RelatorioConsolidadoResponse,
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
                cor_conama=cor_conama_por_categoria(categoria),
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

    def evolucao_temporal(
        self,
        db: Session,
        usuario: dict[str, Any],
        dias: int = 28,
        empresa_id: str | None = None,
        material_id: str | None = None,
    ) -> EvolucaoTemporalResponse:
        """
        Série temporal diária contínua dos últimos `dias` (padrão: 28 dias) para
        gráficos de acompanhamento em tempo real e análise de tendência (RF#015).
        """
        agora = datetime.now(UTC)
        hoje = agora.date()
        inicio_atual = hoje - timedelta(days=dias - 1)
        inicio_anterior = inicio_atual - timedelta(days=dias)
        limite_dt = datetime.combine(inicio_anterior, datetime.min.time())

        query = self._filtrar_escopo_registros(
            db.query(Registro).filter(Registro.created_at >= limite_dt),
            usuario=usuario,
            empresa_id=empresa_id,
            material_id=material_id,
        )
        registros = query.all()

        mapa_dias: dict[date, dict[str, float | int]] = {
            inicio_atual + timedelta(days=i): {
                "total": 0,
                "validados": 0,
                "vol_decl": 0.0,
                "vol_val": 0.0,
                "carbono": 0.0,
                "valor": 0.0,
            }
            for i in range(dias)
        }

        vol_atual = 0.0
        vol_anterior = 0.0
        carb_atual = 0.0
        carb_anterior = 0.0

        for reg in registros:
            dt = reg.created_at
            data_reg = dt.date() if isinstance(dt, datetime) else hoje
            validado = reg.status_validacao == StatusValidacao.VALIDADO
            v_val = float(reg.volume_validado or 0.0) if validado else 0.0
            c_ev = float(reg.carbonoevitado or 0.0) if validado else 0.0
            val_est = float(reg.valorestimado or 0.0) if validado else 0.0

            if inicio_atual <= data_reg <= hoje:
                balde = mapa_dias[data_reg]
                balde["total"] = int(balde["total"]) + 1
                if validado:
                    balde["validados"] = int(balde["validados"]) + 1
                balde["vol_decl"] = float(balde["vol_decl"]) + float(
                    reg.volume_total_original or 0.0
                )
                balde["vol_val"] = float(balde["vol_val"]) + v_val
                balde["carbono"] = float(balde["carbono"]) + c_ev
                balde["valor"] = float(balde["valor"]) + val_est
                vol_atual += v_val
                carb_atual += c_ev
            elif inicio_anterior <= data_reg < inicio_atual:
                vol_anterior += v_val
                carb_anterior += c_ev

        def variacao_pct(atual: float, anterior: float) -> float | None:
            if anterior <= 0:
                return None
            return _arredondar(((atual - anterior) / anterior) * 100.0)

        serie = [
            EvolucaoDiariaItem(
                data=dia.isoformat(),
                total_registros=int(dados["total"]),
                registros_validados=int(dados["validados"]),
                volume_declarado=_arredondar(float(dados["vol_decl"])),
                volume_validado=_arredondar(float(dados["vol_val"])),
                carbono_evitado=_arredondar(float(dados["carbono"]), 4),
                valor_estimado=_arredondar(float(dados["valor"])),
            )
            for dia, dados in sorted(mapa_dias.items())
        ]

        return EvolucaoTemporalResponse(
            dias=dias,
            data_inicio=inicio_atual.isoformat(),
            data_fim=hoje.isoformat(),
            volume_periodo_atual=_arredondar(vol_atual),
            volume_periodo_anterior=_arredondar(vol_anterior),
            variacao_volume_pct=variacao_pct(vol_atual, vol_anterior),
            carbono_periodo_atual=_arredondar(carb_atual, 4),
            carbono_periodo_anterior=_arredondar(carb_anterior, 4),
            variacao_carbono_pct=variacao_pct(carb_atual, carb_anterior),
            serie_diaria=serie,
        )

    def relatorio_consolidado(
        self,
        db: Session,
        usuario: dict[str, Any],
        agrupamento: AgrupamentoRelatorio = AgrupamentoRelatorio.MENSAL,
        empresa_id: str | None = None,
        material_id: str | None = None,
        periodo: str | None = None,
        periodo_inicio: str | None = None,
        periodo_fim: str | None = None,
        data_inicio: str | None = None,
        data_fim: str | None = None,
    ) -> RelatorioConsolidadoResponse:
        """
        Gera relatório consolidado agrupado por período (semanal, mensal ou anual)
        e segmentado por tipo de material (RF#013).
        """
        eh_prefeitura = usuario["user_type"] == "PREFEITURA"
        query = self._filtrar_escopo_registros(
            db.query(Registro).options(joinedload(Registro.material)),
            usuario=usuario,
            empresa_id=empresa_id,
            periodo=periodo,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
            material_id=material_id,
        )
        if data_inicio:
            try:
                query = query.filter(
                    Registro.created_at >= datetime.fromisoformat(data_inicio)
                )
            except ValueError:
                query = query.filter(Registro.periodo >= data_inicio)
        if data_fim:
            try:
                query = query.filter(
                    Registro.created_at <= datetime.fromisoformat(data_fim)
                )
            except ValueError:
                query = query.filter(Registro.periodo <= data_fim)

        registros = query.all()

        def chave_e_rotulo(reg: Registro) -> tuple[str, str]:
            if agrupamento == AgrupamentoRelatorio.ANUAL:
                ano = reg.periodo[:4]
                return ano, f"Ano {ano}"
            if agrupamento == AgrupamentoRelatorio.SEMANAL:
                if isinstance(reg.created_at, datetime):
                    d_ref = reg.created_at.date()
                else:
                    ano_p, mes_p = (int(x) for x in reg.periodo.split("-"))
                    d_ref = date(ano_p, mes_p, 1)
                iso_ano, iso_sem, _ = d_ref.isocalendar()
                inicio_sem = date.fromisocalendar(iso_ano, iso_sem, 1)
                fim_sem = inicio_sem + timedelta(days=6)
                chave = f"{iso_ano}-S{iso_sem:02d}"
                rotulo = (
                    f"Semana {iso_sem:02d}/{iso_ano} "
                    f"({inicio_sem.strftime('%d/%m')} a {fim_sem.strftime('%d/%m')})"
                )
                return chave, rotulo
            # MENSAL
            partes = reg.periodo.split("-")
            rotulo = f"{partes[1]}/{partes[0]}" if len(partes) == 2 else reg.periodo
            return reg.periodo, rotulo

        grupos_map: dict[str, dict[str, Any]] = {}
        materiais_geral: dict[str, dict[str, Any]] = {}

        tot_reg = 0
        tot_pen = 0
        tot_val = 0
        tot_rej = 0
        vol_decl_tot = 0.0
        vol_val_tot = 0.0
        carb_tot = 0.0
        val_tot = 0.0
        soma_perc = 0.0

        for reg in registros:
            chave, rotulo = chave_e_rotulo(reg)
            validado = reg.status_validacao == StatusValidacao.VALIDADO
            pendente = reg.status_validacao == StatusValidacao.PENDENTE
            rejeitado = not validado and not pendente

            v_decl = float(reg.volume_total_original or 0.0)
            v_val = float(reg.volume_validado or 0.0) if validado else 0.0
            c_ev = float(reg.carbonoevitado or 0.0) if validado else 0.0
            v_est = float(reg.valorestimado or 0.0) if validado else 0.0

            tot_reg += 1
            tot_pen += int(pendente)
            tot_val += int(validado)
            tot_rej += int(rejeitado)
            vol_decl_tot += v_decl
            vol_val_tot += v_val
            carb_tot += c_ev
            val_tot += v_est
            soma_perc += float(reg.percentual_reciclado or 0.0)

            grp = grupos_map.setdefault(
                chave,
                {
                    "rotulo": rotulo,
                    "total": 0,
                    "validados": 0,
                    "pendentes": 0,
                    "rejeitados": 0,
                    "vol_decl": 0.0,
                    "vol_val": 0.0,
                    "carbono": 0.0,
                    "valor": 0.0,
                    "materiais": {},
                },
            )
            grp["total"] += 1
            grp["validados"] += int(validado)
            grp["pendentes"] += int(pendente)
            grp["rejeitados"] += int(rejeitado)
            grp["vol_decl"] += v_decl
            grp["vol_val"] += v_val
            grp["carbono"] += c_ev
            grp["valor"] += v_est

            mat_cat = reg.material.categoria if reg.material else reg.material_id
            for destino in (materiais_geral, grp["materiais"]):
                m_entry = destino.setdefault(
                    reg.material_id,
                    {
                        "categoria": mat_cat,
                        "total": 0,
                        "vol_decl": 0.0,
                        "vol_val": 0.0,
                        "carbono": 0.0,
                        "valor": 0.0,
                    },
                )
                m_entry["total"] += 1
                m_entry["vol_decl"] += v_decl
                m_entry["vol_val"] += v_val
                m_entry["carbono"] += c_ev
                m_entry["valor"] += v_est

        def converter_materiais(
            mapa: dict[str, dict[str, Any]],
        ) -> list[EstatisticaMaterialItem]:
            return [
                EstatisticaMaterialItem(
                    material_id=m_id,
                    categoria=d["categoria"],
                    cor_conama=cor_conama_por_categoria(d["categoria"]),
                    total_registros=d["total"],
                    volume_declarado=_arredondar(d["vol_decl"]),
                    volume_validado=_arredondar(d["vol_val"]),
                    carbono_evitado=_arredondar(d["carbono"], 4),
                    valor_estimado=_arredondar(d["valor"]),
                )
                for m_id, d in sorted(
                    mapa.items(), key=lambda par: par[1]["categoria"].lower()
                )
            ]

        grupos = [
            GrupoRelatorioItem(
                chave_periodo=ch,
                rotulo=g["rotulo"],
                total_registros=g["total"],
                registros_validados=g["validados"],
                registros_pendentes=g["pendentes"],
                registros_rejeitados=g["rejeitados"],
                volume_declarado=_arredondar(g["vol_decl"]),
                volume_validado=_arredondar(g["vol_val"]),
                carbono_evitado=_arredondar(g["carbono"], 4),
                valor_estimado=_arredondar(g["valor"]),
                por_material=converter_materiais(g["materiais"]),
            )
            for ch, g in sorted(grupos_map.items())
        ]

        resumo = ResumoRegistrosResponse(
            total_registros=tot_reg,
            registros_pendentes=tot_pen,
            registros_validados=tot_val,
            registros_rejeitados=tot_rej,
            volume_total_declarado=_arredondar(vol_decl_tot),
            volume_total_validado=_arredondar(vol_val_tot),
            carbono_total_evitado=_arredondar(carb_tot, 4),
            valor_total_estimado=_arredondar(val_tot),
            percentual_medio_reciclado=(
                _arredondar(soma_perc / tot_reg) if tot_reg else 0.0
            ),
        )

        municipio = usuario.get("prefeitura_nome")
        if eh_prefeitura and municipio:
            entidade_nome = f"Prefeitura de {municipio}"
        else:
            entidade_nome = usuario["nome"]

        return RelatorioConsolidadoResponse(
            escopo="PREFEITURA" if eh_prefeitura else "EMPRESA",
            entidade_nome=entidade_nome,
            municipio_nome=municipio,
            agrupamento=agrupamento,
            gerado_em=datetime.now(UTC),
            resumo=resumo,
            por_material=converter_materiais(materiais_geral),
            grupos=grupos,
        )


estatisticas_service = EstatisticasService()
