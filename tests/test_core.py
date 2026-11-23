"""Report2Excel 核心单元测试：覆盖数学校验、±35% 历史单价波动、SQLite、PDF/图片加载、Excel 公式与标黄、CLI 端到端。"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from report2excel.cli import main
from report2excel.config import ValidationSettings
from report2excel.demo import DEMO_REPORT_DATA, DemoMockLLM, generate_sample_report, seed_demo_history
from report2excel.excel_export import WARN_FILL, export_excel
from report2excel.extractor import extract_page
from report2excel.history import HistoryStore
from report2excel.ingest import load_inputs, parse_pages
from report2excel.llm import Usage
from report2excel.models import ExtractedPage, LineItem
from report2excel.validator import validate_page


def test_math_error_4x115_reported_450():
    """简历核心用例：4×115 误记为 450，Python 必须检出差额 +10 并标 WARN。"""
    page = ExtractedPage(
        report_date="2026-11-23",
        reported_total=450,
        items=[
            LineItem(
                category="입고",
                item_name="식용유(대)",
                quantity=4,
                unit="통",
                unit_price=115,
                reported_subtotal=450,
            )
        ],
    )
    res = validate_page(page, source_name="t.png", page_label="t.png")
    assert len(res.items) == 1
    item = res.items[0]
    assert item.computed_subtotal == 460
    assert item.subtotal_diff == 10
    assert item.status == "WARN"
    assert "MATH_ERROR" in item.warning_codes
    assert res.total_mismatch is True
    assert res.total_diff == 10


def test_price_deviation_35_percent_boundary(tmp_path: Path):
    """历史均价 ±35% 边界校验：+34% 正常，+36% 与 -40% 报警。"""
    store = HistoryStore(tmp_path / "hist.sqlite3")
    store.add_record(item_name="대파", unit_price=1000, quantity=5, unit="단")
    store.add_record(item_name="대파", unit_price=1000, quantity=5, unit="단")

    page = ExtractedPage(
        report_date="2026-11-23",
        items=[
            LineItem(item_name="대파", quantity=2, unit="단", unit_price=1340, reported_subtotal=2680),
            LineItem(item_name="대파", quantity=2, unit="단", unit_price=1360, reported_subtotal=2720),
            LineItem(item_name="대파", quantity=2, unit="단", unit_price=600, reported_subtotal=1200),
        ],
    )
    res = validate_page(
        page,
        source_name="p.png",
        page_label="p.png",
        history=store,
        settings=ValidationSettings(price_deviation_limit=0.35),
    )
    assert res.items[0].status == "OK"
    assert res.items[1].status == "WARN" and "PRICE_SPIKE" in res.items[1].warning_codes
    assert res.items[2].status == "WARN" and "PRICE_SPIKE" in res.items[2].warning_codes


def test_history_prompt_context_and_warn_not_saved(tmp_path: Path):
    """确认历史 Prompt 上下文生成正确，且默认不把异常行写入历史库污染均价。"""
    store = HistoryStore(tmp_path / "hist.sqlite3")
    seed_demo_history(store)
    ctx = store.build_prompt_context()
    assert "삼겹살" in ctx
    assert "대파" in ctx

    extracted = ExtractedPage.model_validate(DEMO_REPORT_DATA)
    checked = validate_page(extracted, source_name="d.png", page_label="d.png", history=store)
    before = store.count_records()
    saved = store.save_checked_items(checked.items)
    # 5 条中 3 条正常、2 条警告，默认只入库 3 条正常行
    assert saved == 3
    assert store.count_records() == before + 3


def test_extract_retry_on_bad_json_then_succeeds(tmp_path: Path):
    """首次输出坏 JSON 时，抽取器把报错反馈给模型并在下一轮自动修正成功。"""
    png_path, _ = generate_sample_report(tmp_path)
    pages = load_inputs([png_path])

    class FlakyLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages: list[dict]) -> tuple[str, Usage]:
            self.calls += 1
            if self.calls == 1:
                return "not valid json", Usage(prompt_tokens=10, completion_tokens=5, calls=1)
            return json.dumps(DEMO_REPORT_DATA, ensure_ascii=False), Usage(
                prompt_tokens=20, completion_tokens=30, calls=1
            )

    llm = FlakyLLM()
    outcome = extract_page(pages[0], llm, "(없음)", max_attempts=3, retry_base_delay=0)
    assert outcome.extracted is not None
    assert llm.calls == 2
    assert outcome.usage.calls == 2


def test_pdf_and_image_ingest_plus_excel_formulas_and_yellow_highlight(tmp_path: Path):
    """验证 PyMuPDF PDF 解析、Excel 公式写法、以及仅问题行标黄。"""
    png_path, pdf_path = generate_sample_report(tmp_path / "samples")
    assert parse_pages("1-2,4") == [1, 2, 4]

    pdf_pages = load_inputs([pdf_path], pages=[1], dpi=150)
    assert len(pdf_pages) == 1
    assert pdf_pages[0].page_label.endswith("#P1")

    store = HistoryStore(tmp_path / "hist.sqlite3")
    seed_demo_history(store)

    outcome = extract_page(pdf_pages[0], DemoMockLLM(), store.build_prompt_context())
    assert outcome.extracted is not None
    checked = validate_page(
        outcome.extracted,
        source_name=pdf_pages[0].source_name,
        page_label=pdf_pages[0].page_label,
        history=store,
    )

    xlsx = export_excel([checked], tmp_path / "out.xlsx")
    wb = openpyxl.load_workbook(xlsx, data_only=False)
    assert wb.sheetnames == ["일일보고서", "요약"]

    ws = wb["일일보고서"]
    # 第 2 行（삼겹살，正常）：公式存在，且不标黄
    assert ws["I2"].value == "=ROUND(F2*H2,2)"
    assert ws["N2"].value == "정상"
    assert ws["E2"].fill.fill_type is None

    # 第 4 行（식용유(대)，4×115=450 错算）：必须标黄
    assert ws["E4"].value == "식용유(대)"
    assert ws["N4"].value == "경고"
    assert ws["E4"].fill.start_color.rgb.endswith(WARN_FILL.start_color.rgb[-6:])

    # 第 5 行（대파，单价 +63.2%）：必须标黄
    assert ws["E5"].value == "대파"
    assert ws["N5"].value == "경고"
    assert ws["E5"].fill.start_color.rgb.endswith(WARN_FILL.start_color.rgb[-6:])

    # 底部合计行公式（共 5 条明细，数据在第 2~6 行，合计在第 7 行）
    assert ws["I7"].value == "=SUM(I2:I6)"
    assert ws["J7"].value == "=SUM(J2:J6)"
    assert ws["K7"].value == "=I7-J7"

    # 汇总页公式
    ws_sum = wb["요약"]
    assert ws_sum["B5"].value == '=COUNTIF(일일보고서!N2:N6,"경고")'
    assert ws_sum["B6"].value == "=일일보고서!I7"


def test_cli_demo_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """端到端运行 CLI `demo --pdf` 子命令。"""
    monkeypatch.setenv("REPORT2EXCEL_HOME", str(tmp_path / "home"))
    demo_dir = tmp_path / "demo_out"
    rc = main(["demo", "--pdf", "--dir", str(demo_dir)])
    assert rc == 0
    assert (demo_dir / "demo_output.xlsx").exists()
    assert (demo_dir / "samples" / "sample_daily_report.png").exists()
    assert (demo_dir / "samples" / "sample_daily_report.pdf").exists()


def test_history_category_isolation_and_bilingual_alias(tmp_path: Path):
    """进货与销售历史均价互不串台；双语括号品名 '大葱(대파)' 能回退命中 '대파'。"""
    store = HistoryStore(tmp_path / "hist.sqlite3")
    store.add_record(category="입고", item_name="삼겹살", unit_price=18500, quantity=10, unit="kg")
    store.add_record(category="입고", item_name="대파", unit_price=3800, quantity=8, unit="단")

    page = ExtractedPage(
        report_date="11-23",
        items=[
            # 销售单里的 삼겹살 不应与 입고 均价比较
            LineItem(category="매출", item_name="삼겹살", quantity=2, unit="인분", unit_price=10000, reported_subtotal=20000),
            # 双语进货品名 '大葱(대파)' 命中 '대파' 均价 3800 -> +60.5% 触发警告
            LineItem(category="입고", item_name="大葱(대파)", quantity=5, unit="단", unit_price=6100, reported_subtotal=30500),
        ],
    )
    res = validate_page(page, source_name="mix.jpg", page_label="mix.jpg", history=store)
    assert res.items[0].history_avg_price is None
    assert res.items[0].status == "OK"
    assert res.items[1].history_avg_price == 3800
    assert res.items[1].status == "WARN" and "PRICE_SPIKE" in res.items[1].warning_codes
