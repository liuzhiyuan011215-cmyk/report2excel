"""带公式的 Excel 导出器：自动写入小计/差额/单价变动率/合计公式，仅对有问题的行标黄。"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import CheckedItem, PageCheckResult

# 样式定义（清爽商务风，异常行精准标黄）
HEADER_FILL = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
HEADER_FONT = Font(name="Malgun Gothic", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Malgun Gothic", size=10, color="1F2937")
WARN_FILL = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")  # 仅问题行标黄
WARN_FONT = Font(name="Malgun Gothic", size=10, bold=True, color="9A3412")
OK_FONT = Font(name="Malgun Gothic", size=10, color="166534")
TOTAL_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
TOTAL_FONT = Font(name="Malgun Gothic", size=10, bold=True, color="0F172A")
THIN_SIDE = Side(style="thin", color="CBD5E1")
CELL_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)

DETAIL_HEADERS = [
    "날짜",
    "출처(페이지)",
    "거래처/매장",
    "구분",
    "품목명",
    "수량",
    "단위",
    "단가",
    "계산금액(수식)",
    "원본기재금액",
    "차이(수식)",
    "과거평균단가",
    "단가변동률(수식)",
    "검증상태",
    "경고내용",
]


def _num_format(val: float | None) -> str:
    if val is None:
        return "#,##0"
    return "#,##0" if float(val).is_integer() else "#,##0.00"


def _autofit_columns(ws, min_width: int = 9, max_width: int = 44) -> None:
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        longest = 0
        for cell in col:
            text = "" if cell.value is None else str(cell.value)
            # 公式本身可能比显示值长，按合理宽度估算
            if text.startswith("="):
                width = 14
            else:
                # 中韩宽字符按 1.9 宽度估算，避免截断
                width = sum(1.9 if ord(ch) > 127 else 1.0 for ch in text)
            longest = max(longest, width)
        ws.column_dimensions[col_letter].width = max(min_width, min(max_width, longest + 3))


def export_excel(results: list[PageCheckResult], output_path: Path) -> Path:
    """将校验后的各页数据导出为带公式和异常标黄的 .xlsx 文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # ---------------- Sheet 1: 일일보고서（明细） ----------------
    ws = wb.active
    ws.title = "일일보고서"
    ws.freeze_panes = "A2"
    ws.append(DETAIL_HEADERS)
    for col_idx in range(1, len(DETAIL_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = CELL_BORDER
    ws.row_dimensions[1].height = 24

    all_items: list[CheckedItem] = [item for page in results for item in page.items]
    for row_idx, item in enumerate(all_items, start=2):
        # F=수량, H=단가, I=계산금액(수식), J=원본기재금액, K=차이(수식), L=과거평균단가, M=단가변동률(수식)
        row_values = [
            item.report_date,
            item.page_label,
            item.store_or_vendor,
            item.category,
            item.item_name,
            item.quantity,
            item.unit,
            item.unit_price,
            f"=ROUND(F{row_idx}*H{row_idx},2)",
            item.reported_subtotal,
            f'=IF(ISNUMBER(J{row_idx}),I{row_idx}-J{row_idx},"")',
            item.history_avg_price,
            f'=IF(AND(ISNUMBER(L{row_idx}),L{row_idx}>0),(H{row_idx}-L{row_idx})/L{row_idx},"")',
            "경고" if item.status == "WARN" else "정상",
            " / ".join(item.warnings) if item.warnings else item.note,
        ]
        ws.append(row_values)
        is_warn = item.status == "WARN"

        for col_idx in range(1, len(DETAIL_HEADERS) + 1):
            c = ws.cell(row=row_idx, column=col_idx)
            c.border = CELL_BORDER
            c.font = WARN_FONT if (is_warn and col_idx in (14, 15)) else (
                OK_FONT if (not is_warn and col_idx == 14) else BODY_FONT
            )
            if is_warn:
                c.fill = WARN_FILL
            if col_idx in (1, 4, 7, 14):
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in (6, 8, 9, 10, 11, 12, 13):
                c.alignment = Alignment(horizontal="right", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

        ws.cell(row=row_idx, column=6).number_format = _num_format(item.quantity)
        ws.cell(row=row_idx, column=8).number_format = _num_format(item.unit_price)
        ws.cell(row=row_idx, column=9).number_format = _num_format(item.computed_subtotal)
        ws.cell(row=row_idx, column=10).number_format = _num_format(item.reported_subtotal)
        ws.cell(row=row_idx, column=11).number_format = "+#,##0.##;-#,##0.##;0"
        ws.cell(row=row_idx, column=12).number_format = _num_format(item.history_avg_price)
        ws.cell(row=row_idx, column=13).number_format = "+0.0%;-0.0%;0.0%"

    # 底部合计行（全用 Excel 公式）
    last_data_row = len(all_items) + 1
    total_row = last_data_row + 1
    if all_items:
        ws.cell(row=total_row, column=1, value="합계")
        ws.cell(row=total_row, column=5, value=f'=COUNTA(E2:E{last_data_row})&"건"')
        ws.cell(row=total_row, column=9, value=f"=SUM(I2:I{last_data_row})")
        ws.cell(row=total_row, column=10, value=f"=SUM(J2:J{last_data_row})")
        ws.cell(row=total_row, column=11, value=f"=I{total_row}-J{total_row}")
        ws.cell(row=total_row, column=14, value=f'=COUNTIF(N2:N{last_data_row},"경고")&"건 경고"')
        for col_idx in range(1, len(DETAIL_HEADERS) + 1):
            c = ws.cell(row=total_row, column=col_idx)
            c.fill = TOTAL_FILL
            c.font = TOTAL_FONT
            c.border = CELL_BORDER
            if col_idx in (9, 10, 11):
                c.alignment = Alignment(horizontal="right", vertical="center")
                c.number_format = "#,##0.##"
            elif col_idx in (1, 14):
                c.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[total_row].height = 22

    _autofit_columns(ws)

    # ---------------- Sheet 2: 요약（汇总与按页核对） ----------------
    ws_sum = wb.create_sheet("요약")
    ws_sum.append(["항목", "값"])
    for col_idx in (1, 2):
        c = ws_sum.cell(row=1, column=col_idx)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = CELL_BORDER

    summary_rows = [
        ("처리 페이지 수", len(results)),
        ("총 품목 행 수", f"=COUNTA(일일보고서!E2:E{last_data_row})" if all_items else 0),
        ("정상 행 수", f'=COUNTIF(일일보고서!N2:N{last_data_row},"정상")' if all_items else 0),
        ("경고 행 수 (노란색 표시)", f'=COUNTIF(일일보고서!N2:N{last_data_row},"경고")' if all_items else 0),
        ("계산 합계 (Python/Excel 수식)", f"=일일보고서!I{total_row}" if all_items else 0),
        ("원본 소계 합계", f"=일일보고서!J{total_row}" if all_items else 0),
        ("소계 차이 합계", f"=일일보고서!K{total_row}" if all_items else 0),
    ]
    for r_i, (label, val) in enumerate(summary_rows, start=2):
        ws_sum.append([label, val])
        c1, c2 = ws_sum.cell(row=r_i, column=1), ws_sum.cell(row=r_i, column=2)
        c1.font, c2.font = BODY_FONT, TOTAL_FONT
        c1.border = c2.border = CELL_BORDER
        c2.alignment = Alignment(horizontal="right", vertical="center")
        if r_i >= 6:
            c2.number_format = "#,##0.##"

    # 按页合计核对表
    start_row = len(summary_rows) + 4
    page_headers = ["페이지", "날짜", "거래처/매장", "품목수", "계산합계", "원본기재총계", "총계차이", "상태", "비고"]
    for col_idx, text in enumerate(page_headers, start=1):
        c = ws_sum.cell(row=start_row, column=col_idx, value=text)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = CELL_BORDER

    for offset, page in enumerate(results, start=1):
        r = start_row + offset
        has_issue = bool(page.error or page.total_mismatch or any(i.status == "WARN" for i in page.items))
        status_text = "실패" if page.error else ("경고" if has_issue else "정상")
        note_text = page.error or " / ".join(page.page_warnings) or (
            f"품목 경고 {sum(1 for i in page.items if i.status == 'WARN')}건" if has_issue else "이상 없음"
        )
        vals = [
            page.page_label,
            page.report_date,
            page.store_or_vendor,
            len(page.items),
            page.computed_total,
            page.reported_total,
            f'=IF(ISNUMBER(F{r}),E{r}-F{r},"")',
            status_text,
            note_text,
        ]
        for col_idx, val in enumerate(vals, start=1):
            c = ws_sum.cell(row=r, column=col_idx, value=val)
            c.border = CELL_BORDER
            c.font = WARN_FONT if (has_issue and col_idx in (8, 9)) else BODY_FONT
            if has_issue:
                c.fill = WARN_FILL
            if col_idx in (4, 5, 6, 7):
                c.alignment = Alignment(horizontal="right", vertical="center")
                c.number_format = "#,##0.##"
            elif col_idx in (2, 8):
                c.alignment = Alignment(horizontal="center", vertical="center")

    _autofit_columns(ws_sum)
    wb.save(output_path)
    return output_path
