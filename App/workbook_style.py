from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


HEADER_FILL = PatternFill("solid", fgColor="3B5A86")
ROW_FILL_LIGHT = PatternFill("solid", fgColor="E8EEF7")
ROW_FILL_BLUE = PatternFill("solid", fgColor="D6E1F0")
WHITE_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Calibri", size=11, color="172033")
THIN_BLUE = Side(style="thin", color="AFC0D8")
CELL_BORDER = Border(left=THIN_BLUE, right=THIN_BLUE, top=THIN_BLUE, bottom=THIN_BLUE)
CURRENCY_FORMAT = '#,##0.00'
INTEGER_FORMAT = '#,##0'


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.strip().lower().split())


def _is_currency_header(header: object) -> bool:
    normalized = _normalize(header)
    if not normalized:
        return False
    exact_names = {
        "preco",
        "a prazo",
        "a vista",
        "menor preco",
        "preco medio",
        "probel (oficial)",
        "magazine luiza",
        "casas bahia",
        "web continental",
        "casa e video",
        "madeiramadeira",
        "zema",
        "mercado livre",
        "carrefour",
        "site probel",
    }
    if normalized in exact_names:
        return True
    return bool(re.search(r"(^|\s)preco($|\s)", normalized)) and "quantidade" not in normalized


def _is_integer_header(header: object) -> bool:
    normalized = _normalize(header)
    return normalized in {"quantidade de lojas", "quantidade", "qtd", "total"}


def _column_width(header: object, values: Iterable[object]) -> float:
    normalized = _normalize(header)
    if normalized in {"titulo", "produto", "descricao"}:
        return 48.0
    if normalized in {"link", "url", "href"}:
        return 44.0
    if normalized in {"codigo interno", "codigo lojista", "id no canal", "sku"}:
        return 18.0
    if normalized in {"canal", "loja menor preco", "seller menor preco"}:
        return 23.0
    if _is_currency_header(header):
        return 18.0

    lengths = [len(str(header or ""))]
    lengths.extend(len(str(value or "")) for value in values)
    return float(min(32, max(12, max(lengths, default=12) + 2)))


def style_result_worksheet(ws: Worksheet) -> None:
    """Aplica o padrão visual oficial das planilhas de resultado."""
    if ws.max_row < 1 or ws.max_column < 1:
        return

    max_row = ws.max_row
    max_col = ws.max_column
    header_values = [ws.cell(row=1, column=column).value for column in range(1, max_col + 1)]

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(max_col)}{max_row}"
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 90
    ws.row_dimensions[1].height = 36

    for column, header in enumerate(header_values, start=1):
        cell = ws.cell(row=1, column=column)
        cell.fill = HEADER_FILL
        cell.font = WHITE_FONT
        cell.border = CELL_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        sample_values = (
            ws.cell(row=row, column=column).value
            for row in range(2, min(max_row, 80) + 1)
        )
        ws.column_dimensions[get_column_letter(column)].width = _column_width(header, sample_values)

    currency_columns = {
        column
        for column, header in enumerate(header_values, start=1)
        if _is_currency_header(header)
    }
    integer_columns = {
        column
        for column, header in enumerate(header_values, start=1)
        if _is_integer_header(header)
    }

    for row in range(2, max_row + 1):
        fill = ROW_FILL_BLUE if row % 2 == 0 else ROW_FILL_LIGHT
        ws.row_dimensions[row].height = 20
        for column in range(1, max_col + 1):
            cell = ws.cell(row=row, column=column)
            cell.fill = fill
            cell.font = BODY_FONT
            cell.border = CELL_BORDER
            cell.alignment = Alignment(
                horizontal="right" if column in currency_columns or column in integer_columns else "left",
                vertical="center",
                wrap_text=False,
            )
            if column in currency_columns and isinstance(cell.value, (int, float)):
                cell.number_format = CURRENCY_FORMAT
            elif column in integer_columns and isinstance(cell.value, (int, float)):
                cell.number_format = INTEGER_FORMAT


def style_result_workbook(workbook) -> None:
    for worksheet in workbook.worksheets:
        style_result_worksheet(worksheet)
