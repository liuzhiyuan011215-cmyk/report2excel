"""三步向导页面：1) 选择单据  2) 识别与验算  3) 核对标黄并导出带公式 Excel。"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import ValidationSettings
from ..demo import generate_sample_report
from ..excel_export import export_excel
from ..history import HistoryStore
from ..ingest import SUPPORTED_EXTS
from ..llm import Usage
from ..models import CheckedItem, ExtractedPage, LineItem, PageCheckResult
from ..validator import validate_page
from .theme import make_button, make_label

WARN_BG = QColor("#FFF3CD")
WARN_FG = QColor("#9A3412")
OK_FG = QColor("#15803D")


def _fmt_num(val: float | None) -> str:
    if val is None:
        return ""
    return f"{int(val):,}" if float(val).is_integer() else f"{val:,.2f}"


def _parse_float(text: str) -> float | None:
    cleaned = text.strip().replace(",", "").replace("원", "").replace("¥", "").replace("₩", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


# ===================================================================== Step 1: SourcePage
class DropZone(QFrame):
    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(170)

        box = QVBoxLayout(self)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(6)
        title = make_label("把图片、多页 PDF 或整个文件夹拖到这里", "lead")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = make_label("支持 PNG / JPG / WEBP / PDF（可多选，点击此处也可浏览文件）", "caption")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        box.addWidget(sub)

    def _set_dragging(self, active: bool) -> None:
        self.setProperty("dragging", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_dragging(True)

    def dragLeaveEvent(self, event) -> None:
        self._set_dragging(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_dragging(False)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class SourcePage(QWidget):
    # inputs, pages_spec, threshold, mock_mode
    start_requested = Signal(list, str, float, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self._files: list[Path] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(18)

        # 标题行
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(make_label("导入营业报告 / 进货单", "title"))
        titles.addWidget(
            make_label("支持手机拍的手写单据、热敏小票、电脑截图与多页 PDF；AI 抽取后由 Python 独立重算并标黄异常行。", "secondary")
        )
        head.addLayout(titles)
        head.addStretch()
        self.sample_btn = make_button("加载测试单据")
        self.sample_btn.clicked.connect(self._load_samples)
        head.addWidget(self.sample_btn)
        root.addLayout(head)

        # 中间左右两栏：左侧拖放+已选列表，右侧识别参数卡片
        body = QHBoxLayout()
        body.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(12)
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_paths)
        self.drop_zone.clicked.connect(self._browse_files)
        left.addWidget(self.drop_zone)

        btn_row = QHBoxLayout()
        add_files_btn = make_button("选择图片 / PDF")
        add_files_btn.clicked.connect(self._browse_files)
        add_dir_btn = make_button("选择文件夹")
        add_dir_btn.clicked.connect(self._browse_dir)
        self.clear_btn = make_button("清空列表", "danger")
        self.clear_btn.clicked.connect(self.clear_files)
        self.file_count_lbl = make_label("尚未选择文件", "caption")
        btn_row.addWidget(add_files_btn)
        btn_row.addWidget(add_dir_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.file_count_lbl)
        left.addLayout(btn_row)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        left.addWidget(self.file_list, 1)
        body.addLayout(left, 3)

        # 右侧参数卡片
        opts_card = QFrame()
        opts_card.setObjectName("Card")
        opts = QVBoxLayout(opts_card)
        opts.setContentsMargins(20, 20, 20, 20)
        opts.setSpacing(14)
        opts.addWidget(make_label("识别与校验选项", "lead"))

        opts.addWidget(make_label("PDF 页码范围（可选，留空表示全部页）", "caption"))
        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText("例如：1-3,5")
        opts.addWidget(self.pages_edit)

        opts.addWidget(make_label("历史单价波动警告阈值（默认 ±35%）", "caption"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(5, 200)
        self.threshold_spin.setValue(35)
        self.threshold_spin.setSuffix(" %")
        opts.addWidget(self.threshold_spin)

        self.mock_check = QCheckBox("离线演示模式（免 API Key，用内置模拟识别）")
        opts.addWidget(self.mock_check)

        tip = QFrame()
        tip.setObjectName("SubCard")
        tip_box = QVBoxLayout(tip)
        tip_box.setContentsMargins(12, 10, 12, 10)
        tip_box.addWidget(
            make_label(
                "校验规则：\n"
                "• Python 独立重算 数量×单价 与总计，检出手算错误\n"
                "• 结合 SQLite 历史均价（进货/销售分列），超阈值标黄\n"
                "• 导出 Excel 全部填入真实公式，仅问题行标浅黄色",
                "caption",
                wrap=True,
            )
        )
        opts.addWidget(tip)
        opts.addStretch()
        body.addWidget(opts_card, 2)
        root.addLayout(body, 1)

        # 底部启动栏
        foot = QHBoxLayout()
        self.model_hint = make_label("", "caption")
        foot.addWidget(self.model_hint)
        foot.addStretch()
        self.start_btn = make_button("开始识别与验算 →", "primary")
        self.start_btn.setMinimumWidth(180)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._emit_start)
        foot.addWidget(self.start_btn)
        root.addLayout(foot)

    def set_model_hint(self, text: str) -> None:
        self.model_hint.setText(text)

    def add_paths(self, paths: list[Path]) -> None:
        existing = set(self._files)
        added = 0
        for p in paths:
            if not p.exists():
                continue
            if p.is_dir():
                for child in sorted(p.iterdir()):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXTS and child not in existing:
                        self._files.append(child)
                        existing.add(child)
                        added += 1
            elif p.suffix.lower() in SUPPORTED_EXTS and p not in existing:
                self._files.append(p)
                existing.add(p)
                added += 1
        if added:
            self._refresh_list()

    def clear_files(self) -> None:
        self._files.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.file_list.clear()
        for p in self._files:
            tag = "PDF" if p.suffix.lower() == ".pdf" else "IMG"
            item = QListWidgetItem(f"[{tag}]  {p.name}    ({p.parent})")
            self.file_list.addItem(item)
        n = len(self._files)
        self.file_count_lbl.setText(f"已选 {n} 个文件" if n else "尚未选择文件")
        self.start_btn.setEnabled(n > 0)

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片或 PDF 单据",
            str(_project_root()),
            "单据文件 (*.pdf *.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)",
        )
        if files:
            self.add_paths([Path(f) for f in files])

    def _browse_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择包含单据的文件夹", str(_project_root()))
        if folder:
            self.add_paths([Path(folder)])

    def _load_samples(self) -> None:
        suite = _project_root() / "samples" / "test_suite_10"
        if suite.exists() and any(suite.glob("*.jpg")):
            self.clear_files()
            self.add_paths([suite])
            return
        png_path, _ = generate_sample_report(_project_root() / "output" / "demo" / "samples")
        self.clear_files()
        self.add_paths([png_path])

    def _emit_start(self) -> None:
        if not self._files:
            return
        self.start_requested.emit(
            list(self._files),
            self.pages_edit.text().strip(),
            self.threshold_spin.value() / 100.0,
            self.mock_check.isChecked(),
        )


# ===================================================================== Step 2: ProgressPage
class ProgressPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self._start_ts = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(60, 40, 60, 40)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(720)
        card.setMinimumWidth(560)
        box = QVBoxLayout(card)
        box.setContentsMargins(28, 28, 28, 24)
        box.setSpacing(14)

        self.title_lbl = make_label("正在识别单据并进行 Python 独立验算...", "title")
        self.stage_lbl = make_label("准备中...", "secondary")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 0)

        meta = QHBoxLayout()
        self.count_lbl = make_label("0 / 0 页", "caption")
        self.elapsed_lbl = make_label("已用 0.0 秒", "caption")
        meta.addWidget(self.count_lbl)
        meta.addStretch()
        meta.addWidget(self.elapsed_lbl)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(210)

        foot = QHBoxLayout()
        foot.addStretch()
        self.cancel_btn = make_button("取消任务", "danger")
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        foot.addWidget(self.cancel_btn)

        box.addWidget(self.title_lbl)
        box.addWidget(self.stage_lbl)
        box.addWidget(self.bar)
        box.addLayout(meta)
        box.addWidget(self.log_box)
        box.addLayout(foot)
        outer.addWidget(card)

    def start(self) -> None:
        self._start_ts = time.perf_counter()
        self.stage_lbl.setText("正在加载单据页面...")
        self.bar.setRange(0, 0)
        self.count_lbl.setText("准备中...")
        self.elapsed_lbl.setText("已用 0.0 秒")
        self.log_box.clear()
        self.cancel_btn.setEnabled(True)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_stage(self, text: str) -> None:
        self.stage_lbl.setText(text)

    def on_page_done(self, done: int, total: int, label: str, ok: bool, msg: str) -> None:
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        self.count_lbl.setText(f"{done} / {total} 页")
        mark = "✓" if ok else "✗"
        self.log_box.appendPlainText(f"[{done}/{total}] {mark} {label} — {msg}")

    def _tick(self) -> None:
        self.elapsed_lbl.setText(f"已用 {time.perf_counter() - self._start_ts:.1f} 秒")


# ===================================================================== Step 3: ReviewPage
TABLE_HEADERS = [
    "状态",
    "品名",
    "数量",
    "单位",
    "单价",
    "Python小计",
    "原单小计",
    "历史均价",
    "单价变动",
    "警告 / 备注",
    "类别",
    "日期",
    "来源页",
]
EDITABLE_COLS = {1, 2, 3, 4, 6, 9, 10, 11}


class ReviewPage(QWidget):
    restart_requested = Signal()
    history_updated = Signal()

    def __init__(self, history: HistoryStore, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.history = history
        self._results: list[PageCheckResult] = []
        self._page_images: dict[str, bytes] = {}
        self._row_refs: list[tuple[int, int]] = []  # (page_idx, item_idx)
        self._threshold = 0.35
        self._loading_table = False
        self._zoom = 1.0
        self._current_pixmap: QPixmap | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # 顶部 4 张统计卡片
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.stat_total_lbl = self._make_stat_card(stats_row, "明细行数", "0 条", "stat_num")
        self.stat_ok_lbl = self._make_stat_card(stats_row, "校验通过", "0 条", "stat_ok")
        self.stat_warn_lbl = self._make_stat_card(stats_row, "异常警告（标黄）", "0 条", "stat_warn")
        self.stat_sum_lbl = self._make_stat_card(stats_row, "Python 重算总计", "0", "stat_num")
        root.addLayout(stats_row)

        # 工具栏
        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索品名、来源页或警告内容...")
        self.search_edit.setMaximumWidth(280)
        self.search_edit.textChanged.connect(self._apply_filter)

        self.only_warn_chk = QCheckBox("仅看警告行（标黄）")
        self.only_warn_chk.toggled.connect(self._apply_filter)

        add_row_btn = make_button("+ 新增行")
        add_row_btn.clicked.connect(self._add_row)
        del_row_btn = make_button("删除选中行", "danger")
        del_row_btn.clicked.connect(self._delete_selected_row)

        self.meta_lbl = make_label("", "caption")
        bar.addWidget(self.search_edit)
        bar.addWidget(self.only_warn_chk)
        bar.addWidget(add_row_btn)
        bar.addWidget(del_row_btn)
        bar.addStretch()
        bar.addWidget(self.meta_lbl)
        root.addLayout(bar)

        # 中间左右分栏：左侧可编辑表格 + 右侧原图核对
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.table = QTableWidget(0, len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._on_cell_edited)
        self.table.currentCellChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        # 右侧原图面板
        preview_card = QFrame()
        preview_card.setObjectName("SubCard")
        pv_box = QVBoxLayout(preview_card)
        pv_box.setContentsMargins(12, 10, 12, 10)
        pv_box.setSpacing(8)

        pv_head = QHBoxLayout()
        self.preview_title = make_label("原图对照预览（点左侧任意行）", "lead")
        zoom_out = make_button("－")
        zoom_out.setFixedWidth(36)
        zoom_out.clicked.connect(lambda: self._change_zoom(0.8))
        zoom_fit = make_button("适应")
        zoom_fit.clicked.connect(self._fit_preview)
        zoom_in = make_button("＋")
        zoom_in.setFixedWidth(36)
        zoom_in.clicked.connect(lambda: self._change_zoom(1.25))
        pv_head.addWidget(self.preview_title, 1)
        pv_head.addWidget(zoom_out)
        pv_head.addWidget(zoom_fit)
        pv_head.addWidget(zoom_in)
        pv_box.addLayout(pv_head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.preview_img = QLabel("点击左侧任意明细行，这里会显示对应页面的原始单据图片，方便核对手写数字。")
        self.preview_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_img.setWordWrap(True)
        self.scroll.setWidget(self.preview_img)
        pv_box.addWidget(self.scroll, 1)

        splitter.addWidget(preview_card)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, 1)

        # 底部操作栏
        foot = QHBoxLayout()
        back_btn = make_button("← 重新选择单据")
        back_btn.clicked.connect(self.restart_requested.emit)
        self.save_hist_chk = QCheckBox("导出时将正常行写入 SQLite 历史单价库")
        self.save_hist_chk.setChecked(True)
        self.export_btn = make_button("导出带公式 Excel (.xlsx)", "accent")
        self.export_btn.setMinimumWidth(210)
        self.export_btn.clicked.connect(self._export_excel)

        foot.addWidget(back_btn)
        foot.addStretch()
        foot.addWidget(self.save_hist_chk)
        foot.addWidget(self.export_btn)
        root.addLayout(foot)

    def _make_stat_card(self, parent_row: QHBoxLayout, caption: str, value: str, role: str) -> QLabel:
        card = QFrame()
        card.setObjectName("SubCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(2)
        box.addWidget(make_label(caption, "caption"))
        val_lbl = make_label(value, role)
        box.addWidget(val_lbl)
        parent_row.addWidget(card, 1)
        return val_lbl

    def set_data(
        self,
        results: list[PageCheckResult],
        page_images: dict[str, bytes],
        elapsed: float,
        usage: Usage,
        *,
        threshold: float = 0.35,
    ) -> None:
        self._results = results
        self._page_images = page_images
        self._threshold = threshold
        self.meta_lbl.setText(
            f"共 {len(results)} 页 · 耗时 {elapsed:.2f}s · Token {usage.prompt_tokens:,}+{usage.completion_tokens:,}"
        )
        self._rebuild_table()
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
            self._show_preview_for_row(0)

    def _rebuild_table(self) -> None:
        self._loading_table = True
        self.table.setRowCount(0)
        self._row_refs.clear()

        for p_idx, page in enumerate(self._results):
            for i_idx, item in enumerate(page.items):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self._row_refs.append((p_idx, i_idx))
                self._fill_row(row, item)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, max(100, self.table.columnWidth(1)))
        self.table.setColumnWidth(9, min(260, max(140, self.table.columnWidth(9))))
        self.table.setColumnWidth(12, min(160, self.table.columnWidth(12)))
        self._loading_table = False
        self._refresh_stats()
        self._apply_filter()

    def _fill_row(self, row: int, item: CheckedItem) -> None:
        dev_text = f"{item.price_deviation:+.1%}" if item.price_deviation is not None else ""
        status_text = "警告" if item.status == "WARN" else "正常"
        note_text = " / ".join(item.warnings) if item.warnings else item.note
        values = [
            status_text,
            item.item_name,
            _fmt_num(item.quantity),
            item.unit,
            _fmt_num(item.unit_price),
            _fmt_num(item.computed_subtotal),
            _fmt_num(item.reported_subtotal),
            _fmt_num(item.history_avg_price),
            dev_text,
            note_text,
            item.category,
            item.report_date,
            item.page_label,
        ]
        is_warn = item.status == "WARN"
        bold_font = QFont(self.table.font())
        bold_font.setBold(True)

        for col, text in enumerate(values):
            cell = QTableWidgetItem(text)
            if col not in EDITABLE_COLS:
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col in (2, 4, 5, 6, 7, 8):
                cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            elif col in (0, 3, 10, 11):
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if is_warn:
                cell.setBackground(QBrush(WARN_BG))
                if col in (0, 9):
                    cell.setForeground(QBrush(WARN_FG))
                    cell.setFont(bold_font)
            elif col == 0:
                cell.setForeground(QBrush(OK_FG))
                cell.setFont(bold_font)
            self.table.setItem(row, col, cell)

    def _revalidate_page(self, p_idx: int) -> None:
        page = self._results[p_idx]
        extracted = ExtractedPage(
            report_date=page.report_date,
            store_or_vendor=page.store_or_vendor,
            currency=page.currency,
            reported_total=page.reported_total,
            items=[
                LineItem(
                    category=i.category,
                    item_name=i.item_name or "미분류",
                    quantity=i.quantity,
                    unit=i.unit,
                    unit_price=i.unit_price,
                    reported_subtotal=i.reported_subtotal,
                    note=i.note,
                )
                for i in page.items
            ],
        )
        new_page = validate_page(
            extracted,
            source_name=page.source_name,
            page_label=page.page_label,
            history=self.history,
            settings=ValidationSettings(price_deviation_limit=self._threshold),
            prompt_tokens=page.prompt_tokens,
            completion_tokens=page.completion_tokens,
        )
        # 保留每行各自可能编辑过的日期
        for old_item, new_item in zip(page.items, new_page.items):
            if old_item.report_date:
                new_item.report_date = old_item.report_date
        self._results[p_idx] = new_page

    def _on_cell_edited(self, cell: QTableWidgetItem) -> None:
        if self._loading_table:
            return
        row, col = cell.row(), cell.column()
        if row < 0 or row >= len(self._row_refs):
            return
        p_idx, i_idx = self._row_refs[row]
        item = self._results[p_idx].items[i_idx]
        text = cell.text().strip()

        if col == 1:
            item.item_name = text or item.item_name
        elif col == 2:
            val = _parse_float(text)
            if val is not None:
                item.quantity = val
        elif col == 3:
            item.unit = text or "개"
        elif col == 4:
            val = _parse_float(text)
            if val is not None:
                item.unit_price = val
        elif col == 6:
            item.reported_subtotal = _parse_float(text)
        elif col == 9:
            item.note = text
        elif col == 10:
            item.category = text or "입고"
        elif col == 11:
            item.report_date = text

        # 改完数值/品名后，立即用 Python 重新验算该页并刷新这一行标黄状态
        self._revalidate_page(p_idx)
        updated = self._results[p_idx].items[i_idx]
        self._loading_table = True
        self._fill_row(row, updated)
        self._loading_table = False
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        all_items = [i for p in self._results for i in p.items]
        warn_cnt = sum(1 for i in all_items if i.status == "WARN")
        ok_cnt = len(all_items) - warn_cnt
        total_sum = round(sum(i.computed_subtotal for i in all_items), 2)
        self.stat_total_lbl.setText(f"{len(all_items)} 条")
        self.stat_ok_lbl.setText(f"{ok_cnt} 条")
        self.stat_warn_lbl.setText(f"{warn_cnt} 条")
        self.stat_sum_lbl.setText(_fmt_num(total_sum))

    def _apply_filter(self) -> None:
        kw = self.search_edit.text().strip().lower()
        only_warn = self.only_warn_chk.isChecked()
        for row, (p_idx, i_idx) in enumerate(self._row_refs):
            item = self._results[p_idx].items[i_idx]
            match_warn = (not only_warn) or item.status == "WARN"
            hay = f"{item.item_name} {item.page_label} {item.category} {' '.join(item.warnings)}".lower()
            match_kw = (not kw) or (kw in hay)
            self.table.setRowHidden(row, not (match_warn and match_kw))

    def _add_row(self) -> None:
        if not self._results:
            self._results.append(
                PageCheckResult(
                    source_name="manual",
                    page_label="manual",
                    report_date=datetime.now().strftime("%Y-%m-%d"),
                    store_or_vendor="",
                    currency="KRW",
                    items=[],
                    computed_total=0.0,
                    reported_total=None,
                    total_diff=None,
                    total_mismatch=False,
                )
            )
        cur_row = self.table.currentRow()
        p_idx = self._row_refs[cur_row][0] if 0 <= cur_row < len(self._row_refs) else 0
        page = self._results[p_idx]
        page.items.append(
            CheckedItem(
                page_label=page.page_label,
                report_date=page.report_date,
                store_or_vendor=page.store_or_vendor,
                category="입고",
                item_name="新品项",
                quantity=1.0,
                unit="개",
                unit_price=0.0,
                computed_subtotal=0.0,
                reported_subtotal=None,
                subtotal_diff=None,
                history_avg_price=None,
                history_samples=0,
                price_deviation=None,
                status="WARN",
                warning_codes=["INVALID_VALUE"],
                warnings=["请填写单价与数量"],
            )
        )
        self._revalidate_page(p_idx)
        self._rebuild_table()

    def _delete_selected_row(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_refs):
            return
        p_idx, i_idx = self._row_refs[row]
        del self._results[p_idx].items[i_idx]
        self._revalidate_page(p_idx)
        self._rebuild_table()

    def _on_row_selected(self, row: int, _col: int, _prev_r: int, _prev_c: int) -> None:
        self._show_preview_for_row(row)

    def _show_preview_for_row(self, row: int) -> None:
        if row < 0 or row >= len(self._row_refs):
            return
        p_idx, _ = self._row_refs[row]
        page_label = self._results[p_idx].page_label
        self.preview_title.setText(f"原图：{page_label}")
        png_bytes = self._page_images.get(page_label)
        if not png_bytes:
            self._current_pixmap = None
            self.preview_img.setText(f"（{page_label} 无可用预览图）")
            return
        pix = QPixmap()
        pix.loadFromData(QByteArray(png_bytes))
        self._current_pixmap = pix
        self._fit_preview()

    def _fit_preview(self) -> None:
        if not self._current_pixmap or self._current_pixmap.isNull():
            return
        vp = self.scroll.viewport().size()
        target_w = max(220, vp.width() - 16)
        self._zoom = target_w / max(1, self._current_pixmap.width())
        self._render_pixmap()

    def _change_zoom(self, factor: float) -> None:
        if not self._current_pixmap:
            return
        self._zoom = max(0.2, min(3.0, self._zoom * factor))
        self._render_pixmap()

    def _render_pixmap(self) -> None:
        if not self._current_pixmap:
            return
        w = max(120, int(self._current_pixmap.width() * self._zoom))
        scaled = self._current_pixmap.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
        self.preview_img.setPixmap(scaled)

    def _export_excel(self) -> None:
        if not self._results:
            return
        default_dir = _project_root() / "output"
        default_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "保存带公式的 Excel 文件",
            str(default_dir / default_name),
            "Excel 工作簿 (*.xlsx)",
        )
        if not target:
            return
        out_path = Path(target)
        if out_path.suffix.lower() != ".xlsx":
            out_path = out_path.with_suffix(".xlsx")

        export_excel(self._results, out_path)
        saved_msg = ""
        if self.save_hist_chk.isChecked():
            saved = sum(
                self.history.save_checked_items(p.items, source_file=p.source_name)
                for p in self._results
            )
            saved_msg = f"\n同时已将 {saved} 条正常品项写入 SQLite 历史均价库（异常行已自动跳过）。"
            self.history_updated.emit()

        box = QMessageBox(self)
        box.setWindowTitle("导出成功")
        box.setText(f"已生成带公式与异常标黄的 Excel：\n{out_path}{saved_msg}")
        open_btn = box.addButton("立即打开 Excel", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == open_btn:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(out_path)])
            elif sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "", str(out_path)])
