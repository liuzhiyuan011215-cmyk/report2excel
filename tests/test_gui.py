"""GUI 核心交互测试（无头 offscreen 模式）：验证窗口初始化、核对页标黄与行内编辑实时重算消黄。"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from report2excel.demo import DEMO_REPORT_DATA, generate_sample_report, seed_demo_history
from report2excel.gui.app import create_app
from report2excel.gui.main_window import MainWindow
from report2excel.history import HistoryStore
from report2excel.llm import Usage
from report2excel.models import ExtractedPage
from report2excel.validator import validate_page


def test_gui_window_and_inline_revalidation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REPORT2EXCEL_HOME", str(tmp_path / "home"))
    app = create_app([])

    store = HistoryStore(tmp_path / "hist.sqlite3")
    seed_demo_history(store)
    png_path, _ = generate_sample_report(tmp_path / "samples")

    win = MainWindow(history=store)
    win.show()
    app.processEvents()

    # Step 1: 添加文件后按钮启用
    assert not win.source_page.start_btn.isEnabled()
    win.source_page.add_paths([png_path])
    assert win.source_page.start_btn.isEnabled()

    # Step 3: 载入校验结果（含 4×115=450 标黄行与 대파 +63.2% 标黄行）
    extracted = ExtractedPage.model_validate(DEMO_REPORT_DATA)
    checked = validate_page(extracted, source_name=png_path.name, page_label=png_path.name, history=store)
    win.review_page.set_data(
        [checked],
        {png_path.name: png_path.read_bytes()},
        elapsed=1.2,
        usage=Usage(prompt_tokens=100, completion_tokens=50, calls=1),
    )
    win.go(2)
    app.processEvents()

    tbl = win.review_page.table
    assert tbl.rowCount() == 5
    # 第 3 行（索引 2）为 식용유(대)，初始应为“警告”
    assert tbl.item(2, 1).text() == "식용유(대)"
    assert tbl.item(2, 0).text() == "警告"
    assert win.review_page.stat_warn_lbl.text() == "2 条"

    # 把原单小计（第 6 列）从 450 改回 460 -> 立即自动重算并消黄变为“正常”
    tbl.item(2, 6).setText("460")
    app.processEvents()
    assert tbl.item(2, 0).text() == "正常"
    assert win.review_page.stat_warn_lbl.text() == "1 条"

    win.close()
