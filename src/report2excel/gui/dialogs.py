"""弹窗：模型与阈值设置弹窗 + SQLite 历史单价库管理弹窗。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..config import LLM_PRESETS, clean_pasted_key, load_settings, save_settings
from ..demo import seed_demo_history
from ..history import HistoryStore
from ..llm import FatalLLMError, check_connection, explain_error
from .theme import make_button, make_label


class SettingsDialog(QDialog):
    def __init__(self, parent=None, notice: str = ""):
        super().__init__(parent)
        self.setWindowTitle("设置 · 多模态模型与校验参数")
        self.setMinimumWidth(520)
        self.settings = load_settings()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        if notice:
            warn = make_label(notice, "secondary", wrap=True)
            warn.setStyleSheet("color: #B45309; background: #FFFBEB; padding: 10px; border-radius: 8px;")
            root.addWidget(warn)

        form = QFormLayout()
        form.setSpacing(10)

        self.preset_combo = QComboBox()
        for key in LLM_PRESETS:
            self.preset_combo.addItem(key, key)
        if self.settings.llm.provider in LLM_PRESETS:
            self.preset_combo.setCurrentText(self.settings.llm.provider)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        form.addRow("模型预设", self.preset_combo)

        self.base_url_edit = QLineEdit(self.settings.llm.base_url)
        form.addRow("接口地址", self.base_url_edit)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self._fill_models(self.settings.llm.provider, self.settings.llm.model)
        form.addRow("模型名称", self.model_combo)

        key_row = QHBoxLayout()
        self.key_edit = QLineEdit(self.settings.llm.api_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("粘贴 API Key（本地接口填 dummy）")
        toggle_btn = make_button("显示")
        toggle_btn.setCheckable(True)
        toggle_btn.toggled.connect(
            lambda checked: (
                self.key_edit.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                ),
                toggle_btn.setText("隐藏" if checked else "显示"),
            )
        )
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(toggle_btn)
        form.addRow("API Key", key_row)

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(5, 200)
        self.threshold_spin.setValue(int(round(self.settings.validation.price_deviation_limit * 100)))
        self.threshold_spin.setSuffix(" %")
        form.addRow("默认单价警戒", self.threshold_spin)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 8)
        self.workers_spin.setValue(self.settings.max_workers)
        form.addRow("并发识别页数", self.workers_spin)

        root.addLayout(form)

        foot = QHBoxLayout()
        test_btn = make_button("测试连接")
        test_btn.clicked.connect(self._test_connection)
        cancel_btn = make_button("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = make_button("保存设置", "primary")
        save_btn.clicked.connect(self._save_and_accept)
        foot.addWidget(test_btn)
        foot.addStretch()
        foot.addWidget(cancel_btn)
        foot.addWidget(save_btn)
        root.addLayout(foot)

    def _fill_models(self, provider: str, current_model: str) -> None:
        self.model_combo.clear()
        preset = LLM_PRESETS.get(provider, {})
        for m in preset.get("models", []):
            self.model_combo.addItem(m)
        self.model_combo.setCurrentText(current_model)

    def _on_preset_changed(self, name: str) -> None:
        if name not in LLM_PRESETS:
            return
        self.settings.llm.apply_preset(name)
        self.base_url_edit.setText(self.settings.llm.base_url)
        self._fill_models(name, self.settings.llm.model)
        if "default_key" in LLM_PRESETS[name]:
            self.key_edit.setText(LLM_PRESETS[name]["default_key"])

    def _collect(self):
        s = self.settings.model_copy(deep=True)
        s.llm.provider = self.preset_combo.currentText()
        s.llm.base_url = self.base_url_edit.text().strip()
        s.llm.model = self.model_combo.currentText().strip()
        cleaned, _ = clean_pasted_key(self.key_edit.text())
        s.llm.api_key = cleaned
        preset = LLM_PRESETS.get(s.llm.provider, {})
        s.llm.json_mode = preset.get("json_mode", True)
        s.llm.extra_body = dict(preset.get("extra_body", {}))
        s.validation.price_deviation_limit = self.threshold_spin.value() / 100.0
        s.max_workers = self.workers_spin.value()
        return s

    def _test_connection(self) -> None:
        s = self._collect()
        if not s.llm.ready:
            QMessageBox.warning(self, "未填写 Key", "请先粘贴 API Key。")
            return
        try:
            msg = check_connection(s.llm)
            QMessageBox.information(self, "连接成功", msg)
        except Exception as exc:
            detail = str(exc) if isinstance(exc, FatalLLMError) else explain_error(exc)
            QMessageBox.critical(self, "连接失败", detail)

    def _save_and_accept(self) -> None:
        s = self._collect()
        save_settings(s)
        self.accept()


class HistoryDialog(QDialog):
    def __init__(self, history: HistoryStore, parent=None):
        super().__init__(parent)
        self.history = history
        self.setWindowTitle("SQLite 历史品项 · 单价基准库")
        self.resize(700, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        self.info_lbl = make_label("", "secondary")
        root.addWidget(self.info_lbl)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["品名", "历史平均单价", "最近单价", "最低~最高", "常用单位", "累计样本"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)

        foot = QHBoxLayout()
        seed_btn = make_button("导入演示历史基线")
        seed_btn.clicked.connect(self._seed)
        clear_btn = make_button("清空历史库", "danger")
        clear_btn.clicked.connect(self._clear)
        close_btn = make_button("关闭", "primary")
        close_btn.clicked.connect(self.accept)
        foot.addWidget(seed_btn)
        foot.addWidget(clear_btn)
        foot.addStretch()
        foot.addWidget(close_btn)
        root.addLayout(foot)

        self.refresh()

    def refresh(self) -> None:
        rows = self.history.list_item_summaries(limit=200)
        self.info_lbl.setText(
            f"数据库：{self.history.path}   |   累计记录 {self.history.count_records()} 条，品项 {len(rows)} 种"
        )
        self.table.setRowCount(0)
        for s in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [
                s.item_name,
                f"{s.avg_unit_price:,.0f}" if s.avg_unit_price.is_integer() else f"{s.avg_unit_price:,.2f}",
                f"{s.last_unit_price:,.0f}" if s.last_unit_price.is_integer() else f"{s.last_unit_price:,.2f}",
                f"{s.min_unit_price:,.0f} ~ {s.max_unit_price:,.0f}",
                s.common_unit,
                f"{s.sample_count} 次",
            ]
            for c, text in enumerate(vals):
                item = QTableWidgetItem(text)
                if c in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif c in (4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def _seed(self) -> None:
        n = seed_demo_history(self.history)
        self.refresh()
        QMessageBox.information(self, "已写入", f"已写入 {n} 条餐厅采购历史记录，用于 ±35% 单价波动校验。")

    def _clear(self) -> None:
        if QMessageBox.question(self, "确认清空", "确定清空全部历史单价记录吗？") == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh()
