from fpdf import FPDF

from src.schemas.schemas import RelatorioConsolidadoResponse


def _texto_pdf(texto: str) -> str:
    """Garante compatibilidade com fontes core Latin-1/CP1252 do PDF."""
    substituicoes = {
        "₂": "2",
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "’": "'",
    }
    for orig, dest in substituicoes.items():
        texto = texto.replace(orig, dest)
    return texto.encode("cp1252", errors="replace").decode("cp1252")


def _hex_para_rgb(cor_hex: str) -> tuple[int, int, int]:
    limpo = cor_hex.lstrip("#")
    if len(limpo) != 6:
        return (108, 117, 125)
    return (int(limpo[0:2], 16), int(limpo[2:4], 16), int(limpo[4:6], 16))


class _RelatorioPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 120, 100)
        rodape = (
            f"ColetaCarbono - Metodologia IPCC / CONAMA 275 | Página {self.page_no()}"
        )
        self.cell(0, 8, _texto_pdf(rodape), align="C")


def gerar_pdf_relatorio(relatorio: RelatorioConsolidadoResponse) -> bytes:
    """
    Gera o arquivo PDF do relatório consolidado de emissões evitadas (RF#014),
    aplicando paleta ecológica verde e indicadores CONAMA 275 (RNF#002).
    """
    pdf = _RelatorioPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    # Cabeçalho ecológico verde
    pdf.set_fill_color(27, 94, 32)  # Verde floresta (#1B5E20)
    pdf.rect(10, 10, 190, 26, style="F")

    pdf.set_xy(15, 13)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(
        0,
        8,
        _texto_pdf("Relatório Consolidado de Impacto de Carbono"),
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 10)
    subtitulo = (
        f"Entidade: {relatorio.entidade_nome} | "
        f"Agrupamento: {relatorio.agrupamento.value.capitalize()} | "
        f"Emitido em: {relatorio.gerado_em.strftime('%d/%m/%Y %H:%M UTC')}"
    )
    pdf.cell(0, 6, _texto_pdf(subtitulo), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)

    # Cards de KPIs principais
    resumo = relatorio.resumo
    val_tot_str = f"{resumo.registros_validados} / {resumo.total_registros}"
    cards = [
        ("Registros (Val/Tot)", val_tot_str),
        ("Volume Validado (t)", f"{resumo.volume_total_validado:,.2f}"),
        ("CO2 Evitado (tCO2eq)", f"{resumo.carbono_total_evitado:,.4f}"),
        ("Valor Estimado (R$)", f"R$ {resumo.valor_total_estimado:,.2f}"),
    ]

    x_inicial = 10.0
    largura_card = 45.25
    y_cards = pdf.get_y()
    for indice, (titulo, valor) in enumerate(cards):
        x = x_inicial + indice * (largura_card + 3.0)
        pdf.set_fill_color(232, 245, 233)  # Verde claro (#E8F5E9)
        pdf.set_draw_color(165, 214, 167)
        pdf.rect(x, y_cards, largura_card, 18, style="DF")

        pdf.set_xy(x + 2, y_cards + 2.5)
        pdf.set_text_color(46, 125, 50)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(largura_card - 4, 5, _texto_pdf(titulo))

        pdf.set_xy(x + 2, y_cards + 9)
        pdf.set_text_color(27, 45, 27)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(largura_card - 4, 6, _texto_pdf(valor))

    pdf.set_y(y_cards + 24)

    # Seção 1: Segmentação por Tipo de Material (CONAMA 275)
    pdf.set_text_color(27, 94, 32)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(
        0,
        8,
        _texto_pdf("1. Consolidado por Tipo de Material (CONAMA 275)"),
        new_x="LMARGIN",
        new_y="NEXT",
    )

    col_mat = [46, 24, 38, 42, 40]
    cab_mat = [
        "Material",
        "Registros",
        "Vol. Validado (t)",
        "CO2 Evitado (t)",
        "Valor Est. (R$)",
    ]

    pdf.set_fill_color(46, 125, 50)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    for larg, texto in zip(col_mat, cab_mat, strict=True):
        pdf.cell(larg, 7, _texto_pdf(texto), border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(33, 37, 41)
    if not relatorio.por_material:
        msg_vazio = _texto_pdf("Nenhum registro encontrado para os filtros.")
        pdf.cell(sum(col_mat), 7, msg_vazio, border=1, align="C")
        pdf.ln()
    else:
        for item in relatorio.por_material:
            y_linha = pdf.get_y()
            x_linha = pdf.get_x()
            r, g, b = _hex_para_rgb(item.cor_conama)

            pdf.cell(col_mat[0], 7, _texto_pdf(f"    {item.categoria}"), border=1)
            # Marcador colorido CONAMA 275
            pdf.set_fill_color(r, g, b)
            pdf.rect(x_linha + 2, y_linha + 2, 3, 3, style="F")

            pdf.cell(col_mat[1], 7, str(item.total_registros), border=1, align="C")
            pdf.cell(col_mat[2], 7, f"{item.volume_validado:,.2f}", border=1, align="R")
            pdf.cell(col_mat[3], 7, f"{item.carbono_evitado:,.4f}", border=1, align="R")
            pdf.cell(col_mat[4], 7, f"{item.valor_estimado:,.2f}", border=1, align="R")
            pdf.ln()

    pdf.ln(6)

    # Seção 2: Consolidação por Período
    pdf.set_text_color(27, 94, 32)
    pdf.set_font("Helvetica", "B", 12)
    titulo_per = f"2. Evolução por Período ({relatorio.agrupamento.value.capitalize()})"
    pdf.cell(0, 8, _texto_pdf(titulo_per), new_x="LMARGIN", new_y="NEXT")

    col_per = [58, 22, 34, 38, 38]
    cab_per = [
        "Período",
        "Val/Tot",
        "Vol. Validado (t)",
        "CO2 Evitado (t)",
        "Valor Est. (R$)",
    ]

    pdf.set_fill_color(46, 125, 50)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    for larg, texto in zip(col_per, cab_per, strict=True):
        pdf.cell(larg, 7, _texto_pdf(texto), border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(33, 37, 41)
    if not relatorio.grupos:
        msg_sem_per = _texto_pdf("Nenhum período registrado.")
        pdf.cell(sum(col_per), 7, msg_sem_per, border=1, align="C")
        pdf.ln()
    else:
        for grp in relatorio.grupos:
            pdf.cell(col_per[0], 7, _texto_pdf(grp.rotulo[:32]), border=1)
            pdf.cell(
                col_per[1],
                7,
                f"{grp.registros_validados}/{grp.total_registros}",
                border=1,
                align="C",
            )
            pdf.cell(col_per[2], 7, f"{grp.volume_validado:,.2f}", border=1, align="R")
            pdf.cell(col_per[3], 7, f"{grp.carbono_evitado:,.4f}", border=1, align="R")
            pdf.cell(col_per[4], 7, f"{grp.valor_estimado:,.2f}", border=1, align="R")
            pdf.ln()

    return bytes(pdf.output())
