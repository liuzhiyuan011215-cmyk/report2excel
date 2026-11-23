"""界面主题与基础视觉组件：复刻 CardMaker 的苹果磨砂玻璃底 + shadcn/ui 风格控件。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

ASSETS_DIR = Path(__file__).parent / "assets"
SHADOW_RGB = (16, 24, 40)


def _font_css() -> tuple[str, str]:
    if sys.platform == "win32":
        return '"Segoe UI", "Microsoft YaHei UI", "Malgun Gothic", sans-serif', "Consolas"
    return '-apple-system, "PingFang SC", "Apple SD Gothic Neo", sans-serif', "Menlo"


def build_stylesheet() -> str:
    ui_font, mono_font = _font_css()
    return f"""
* {{ outline: none; }}
QWidget {{ color: #0A0A0A; font-family: {ui_font}; font-size: 14px; }}
QMainWindow {{ background: #EDF0F3; }}
QDialog, QMessageBox {{ background: #FFFFFF; }}
#Header, #Page {{ background: transparent; }}
QFrame#Sheet {{
    background: #FFFFFF;
    border: 1px solid rgba(255, 255, 255, 210);
    border-radius: 24px;
}}
QFrame#Card {{
    background: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 14px;
}}
QFrame#SubCard {{
    background: #FAFAFA;
    border: 1px solid #E5E5E5;
    border-radius: 12px;
}}
QFrame#DropZone {{
    background: #FAFAFA;
    border: 2px dashed #D4D4D4;
    border-radius: 16px;
}}
QFrame#DropZone[dragging="true"] {{
    background: #ECFDF5;
    border: 2px dashed #059669;
}}

/* 文字层级 */
QLabel {{ background: transparent; }}
QLabel[role="AppTitle"] {{ font-size: 17px; font-weight: 700; color: #0A0A0A; }}
QLabel[role="AppSubtitle"] {{ font-size: 12px; color: #737373; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 600; color: #0A0A0A; }}
QLabel[role="lead"] {{ font-size: 15px; font-weight: 600; color: #0A0A0A; }}
QLabel[role="secondary"] {{ font-size: 13px; color: #525252; }}
QLabel[role="caption"] {{ font-size: 12px; color: #737373; }}
QLabel[role="stat_num"] {{ font-size: 20px; font-weight: 700; color: #0A0A0A; }}
QLabel[role="stat_warn"] {{ font-size: 20px; font-weight: 700; color: #B45309; }}
QLabel[role="stat_ok"] {{ font-size: 20px; font-weight: 700; color: #15803D; }}

/* 按钮（shadcn 风格） */
QPushButton {{
    background: #FFFFFF;
    color: #0A0A0A;
    border: 1px solid #E5E5E5;
    border-radius: 8px;
    padding: 0 14px;
    min-height: 36px;
    font-weight: 500;
}}
QPushButton:hover {{ background: #F5F5F5; border-color: #D4D4D4; }}
QPushButton:pressed {{ background: #EBEBEB; }}
QPushButton:disabled {{ background: #FAFAFA; color: #A3A3A3; border-color: #E5E5E5; }}

QPushButton[variant="primary"] {{
    background: #171717;
    color: #FAFAFA;
    border: 1px solid #171717;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: #2E2E2E; }}
QPushButton[variant="primary"]:pressed {{ background: #0A0A0A; }}
QPushButton[variant="primary"]:disabled {{ background: #D4D4D4; border-color: #D4D4D4; color: #FFFFFF; }}

QPushButton[variant="accent"] {{
    background: #059669;
    color: #FFFFFF;
    border: 1px solid #059669;
    font-weight: 600;
}}
QPushButton[variant="accent"]:hover {{ background: #047857; }}

QPushButton[variant="ghost"] {{
    background: rgba(255, 255, 255, 130);
    border: 1px solid rgba(255, 255, 255, 200);
    border-radius: 10px;
    color: #171717;
}}
QPushButton[variant="ghost"]:hover {{ background: rgba(255, 255, 255, 210); }}

QPushButton[variant="danger"] {{
    background: #FFFFFF;
    color: #DC2626;
    border: 1px solid #FECACA;
}}
QPushButton[variant="danger"]:hover {{ background: #FEF2F2; }}

/* 输入控件 */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 8px;
    padding: 0 10px;
    min-height: 36px;
    color: #0A0A0A;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid #171717;
}}
QPlainTextEdit, QListWidget {{
    background: #FAFAFA;
    border: 1px solid #E5E5E5;
    border-radius: 10px;
    padding: 6px;
    font-family: {mono_font};
    font-size: 12px;
}}

/* 进度条 */
QProgressBar {{
    background: #EBEBEB;
    border: none;
    border-radius: 6px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: #059669;
    border-radius: 6px;
}}

/* 表格 */
QTableWidget {{
    background: #FFFFFF;
    border: 1px solid #E5E5E5;
    border-radius: 10px;
    gridline-color: #EFEFEF;
    selection-background-color: #DBEAFE;
    selection-color: #0A0A0A;
}}
QHeaderView::section {{
    background: #F8FAFC;
    color: #334155;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 6px;
    border: none;
    border-bottom: 1px solid #E2E8F0;
    border-right: 1px solid #F1F5F9;
}}

QCheckBox {{ spacing: 8px; }}
"""


def install_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#EDF0F3"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#0A0A0A"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#0A0A0A"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#0A0A0A"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#DBEAFE"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#0A0A0A"))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet())


def make_label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def make_button(text: str, variant: str = "") -> QPushButton:
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class Backdrop(QWidget):
    """CardMaker 同款磨砂玻璃背景：浅灰底 + 三团柔和彩光 + 浮层面板阴影。"""

    BLOBS = (
        ((0.0, 0.0, 0.8), "#D3EBE3"),
        ((1.0, 0.1, 0.65), "#D6E2F8"),
        ((0.2, 1.0, 0.7), "#E5E0F6"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sheet: QWidget | None = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, QColor("#EDF0F3"))
        for (fx, fy, fr), hex_color in self.BLOBS:
            grad = QRadialGradient(
                QPointF(rect.width() * fx, rect.height() * fy),
                max(rect.width(), rect.height()) * fr,
            )
            inner, outer = QColor(hex_color), QColor(hex_color)
            outer.setAlpha(0)
            grad.setColorAt(0, inner)
            grad.setColorAt(1, outer)
            painter.fillRect(rect, grad)
        if self.sheet is not None and self.sheet.isVisible():
            sr = QRectF(self.sheet.geometry())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*SHADOW_RGB, 3))
            for spread in range(2, 24, 2):
                painter.drawRoundedRect(
                    sr.adjusted(-spread, -spread + 8, spread, spread + 8),
                    24 + spread,
                    24 + spread,
                )


class StepIndicator(QWidget):
    """CardMaker 同款半透明胶囊步骤条：切换步骤时白色胶囊平滑滑动。"""

    def __init__(self, steps: list[str], parent=None):
        super().__init__(parent)
        self._steps = steps
        self._current = 0
        self._pill_x = 4.0
        self._pill_w = 110.0
        self._labels: list[QLabel] = []
        self.setFixedHeight(42)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(4)
        for idx, text in enumerate(steps):
            lbl = QLabel(f"{idx + 1}. {text}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setContentsMargins(14, 0, 14, 0)
            row.addWidget(lbl)
            self._labels.append(lbl)

        self._anim_x = QPropertyAnimation(self, b"pill_x", self)
        self._anim_x.setDuration(220)
        self._anim_x.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_w = QPropertyAnimation(self, b"pill_w", self)
        self._anim_w.setDuration(220)
        self._anim_w.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._refresh_styles()

    def _get_pill_x(self) -> float:
        return self._pill_x

    def _set_pill_x(self, val: float) -> None:
        self._pill_x = val
        self.update()

    def _get_pill_w(self) -> float:
        return self._pill_w

    def _set_pill_w(self, val: float) -> None:
        self._pill_w = val
        self.update()

    pill_x = Property(float, _get_pill_x, _set_pill_x)
    pill_w = Property(float, _get_pill_w, _set_pill_w)

    def _refresh_styles(self) -> None:
        for i, lbl in enumerate(self._labels):
            font = QFont(lbl.font())
            font.setBold(i == self._current)
            lbl.setFont(font)
            color = "#0A0A0A" if i == self._current else ("#059669" if i < self._current else "#737373")
            lbl.setStyleSheet(f"color: {color}; font-size: 13px; background: transparent;")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._snap_pill()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._snap_pill()

    def _snap_pill(self) -> None:
        g = self._labels[self._current].geometry()
        if g.width() > 0:
            self._pill_x = float(g.x())
            self._pill_w = float(g.width())
            self.update()

    def set_current(self, index: int) -> None:
        index = max(0, min(index, len(self._steps) - 1))
        self._current = index
        self._refresh_styles()
        g = self._labels[index].geometry()
        if g.width() <= 0:
            return
        self._anim_x.stop()
        self._anim_w.stop()
        self._anim_x.setStartValue(self._pill_x)
        self._anim_x.setEndValue(float(g.x()))
        self._anim_w.setStartValue(self._pill_w)
        self._anim_w.setEndValue(float(g.width()))
        self._anim_x.start()
        self._anim_w.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QColor(255, 255, 255, 130))
        painter.setPen(QColor(255, 255, 255, 210))
        painter.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        pill = QRectF(self._pill_x, 4.0, self._pill_w, self.height() - 8.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)


class AppLogo(QWidget):
    """左上角圆形/圆角图标显示控件；无图片文件时自动绘制简约表格徽章。"""

    def __init__(self, size: int = 40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        icon_file = ASSETS_DIR / "icon.png"
        self._image = QImage(str(icon_file)) if icon_file.exists() else None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        if self._image and not self._image.isNull():
            painter.drawImage(rect, self._image)
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#059669"))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor("#FFFFFF"))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSize(13)
        painter.setFont(f)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "XL")
