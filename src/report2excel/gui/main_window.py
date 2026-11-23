"""主窗口：复刻 CardMaker 磨砂玻璃三步向导骨架（导入单据 → 识别验算 → 核对并导出）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import load_settings
from ..history import HistoryStore
from .dialogs import HistoryDialog, SettingsDialog
from .pages import ProgressPage, ReviewPage, SourcePage
from .theme import AppLogo, Backdrop, StepIndicator, make_button, make_label
from .worker import ConvertWorker

STEPS = ["选择单据", "识别与验算", "核对并导出"]


class MainWindow(QMainWindow):
    def __init__(self, history: HistoryStore | None = None):
        super().__init__()
        self.setWindowTitle("Report2Excel · 图片/PDF 营业报告转公式 Excel")
        self.resize(1240, 820)
        self.setMinimumSize(1020, 680)
        self.history = history or HistoryStore()
        self.worker: ConvertWorker | None = None
        self._last_threshold = 0.35

        # 三层视觉结构：磨砂玻璃底 Backdrop → 白色大圆角浮层 Sheet → 页面内容
        central = Backdrop()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 0, 24, 24)
        root.setSpacing(0)

        # 顶部三列：左 Logo+标题，中 胶囊步骤条，右 历史库+设置
        header = QWidget()
        header.setObjectName("Header")
        head = QGridLayout(header)
        head.setContentsMargins(8, 16, 8, 16)
        head.setColumnStretch(0, 1)
        head.setColumnStretch(2, 1)

        left = QHBoxLayout()
        left.addWidget(AppLogo(40))
        left.addSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("Report2Excel", "AppTitle"))
        titles.addWidget(make_label("图片 / PDF 营业报告自动验算并生成公式 Excel", "AppSubtitle"))
        left.addLayout(titles)
        left.addStretch()
        head.addLayout(left, 0, 0)

        self.steps = StepIndicator(STEPS)
        head.addWidget(self.steps, 0, 1)

        right = QHBoxLayout()
        right.addStretch()
        self.history_btn = make_button("历史单价库", "ghost")
        self.history_btn.clicked.connect(self.open_history)
        self.settings_btn = make_button("设置", "ghost")
        self.settings_btn.clicked.connect(lambda: self.open_settings())
        right.addWidget(self.history_btn)
        right.addWidget(self.settings_btn)
        head.addLayout(right, 0, 2)
        root.addWidget(header)

        # 白色圆角面板
        self.stack = QStackedWidget()
        self.source_page = SourcePage()
        self.progress_page = ProgressPage()
        self.review_page = ReviewPage(self.history)
        for page in (self.source_page, self.progress_page, self.review_page):
            self.stack.addWidget(page)

        sheet = QFrame()
        sheet.setObjectName("Sheet")
        sheet_box = QVBoxLayout(sheet)
        sheet_box.setContentsMargins(0, 0, 0, 0)
        sheet_box.addWidget(self.stack)
        central.sheet = sheet
        root.addWidget(sheet, 1)
        self.setCentralWidget(central)

        self.source_page.start_requested.connect(self.start_convert)
        self.progress_page.cancel_requested.connect(self.cancel_convert)
        self.review_page.restart_requested.connect(lambda: self.go(0))
        self._sync_model_hint()

    def go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.steps.set_current(index)

    def _sync_model_hint(self) -> None:
        s = load_settings()
        cnt = self.history.count_records()
        status = f"当前模型：{s.llm.provider} / {s.llm.model}" if s.llm.ready else "尚未配置 API Key（点右上角「设置」或勾选离线演示模式）"
        self.source_page.set_model_hint(f"{status}   ·   历史单价库：{cnt} 条")
        self.source_page.threshold_spin.setValue(int(round(s.validation.price_deviation_limit * 100)))

    def open_settings(self, notice: str = "") -> bool:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "正在识别", "当前有任务正在运行，完成后再修改设置。")
            return False
        dlg = SettingsDialog(self, notice=notice)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._sync_model_hint()
            return True
        return False

    def open_history(self) -> None:
        HistoryDialog(self.history, self).exec()
        self._sync_model_hint()

    def start_convert(self, inputs: list[Path], pages_spec: str, threshold: float, mock_mode: bool) -> None:
        settings = load_settings()
        if not mock_mode and not settings.llm.ready:
            if not self.open_settings("开始识别前请先配置 API Key（或选择本地接口预设 / 勾选离线演示模式）。"):
                return
            settings = load_settings()
            if not settings.llm.ready:
                return

        self._last_threshold = threshold
        self.progress_page.start()
        self.go(1)

        self.worker = ConvertWorker(
            inputs,
            settings,
            self.history,
            pages_spec=pages_spec,
            threshold=threshold,
            mock_mode=mock_mode,
            parent=self,
        )
        self.worker.stage_changed.connect(self.progress_page.set_stage)
        self.worker.page_progress.connect(self.progress_page.on_page_done)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def cancel_convert(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.progress_page.set_stage("正在取消任务...")
            self.progress_page.cancel_btn.setEnabled(False)

    def _on_completed(self, results, page_images, elapsed: float, usage) -> None:
        self.progress_page.stop()
        self.review_page.set_data(results, page_images, elapsed, usage, threshold=self._last_threshold)
        self.go(2)

    def _on_failed(self, msg: str) -> None:
        self.progress_page.stop()
        self.go(0)
        if "取消" not in msg:
            QMessageBox.critical(self, "识别未完成", msg)

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        super().closeEvent(event)
