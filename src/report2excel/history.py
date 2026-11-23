"""SQLite 历史品项·单价库：为多模态识别提供参考，并为 ±35% 单价波动校验提供基准。"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import db_path as default_db_path
from .models import CheckedItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS item_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    report_date TEXT NOT NULL,
    category TEXT NOT NULL,
    item_name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL,
    source_file TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_item_history_norm ON item_history(norm_name);
"""


@dataclass
class PriceStats:
    item_name: str
    avg_unit_price: float
    last_unit_price: float
    min_unit_price: float
    max_unit_price: float
    common_unit: str
    sample_count: int


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def _candidate_names(name: str) -> list[str]:
    """全名优先，查不到时再尝试括号内/外别名（如 '大葱(대파)' -> '대파', '大葱'）。"""
    primary = normalize_name(name)
    if not primary:
        return []
    candidates = [primary]
    for inner in re.findall(r"[（(]([^()（）]+)[)）]", name):
        n = normalize_name(inner)
        if n and n not in candidates:
            candidates.append(n)
    outer = normalize_name(re.sub(r"[（(][^()（）]+[)）]", "", name))
    if outer and outer not in candidates:
        candidates.append(outer)
    return candidates


class HistoryStore:
    """每次操作单独打开连接，确保后续 GUI 后台线程与主线程访问安全。"""

    def __init__(self, path: Path | None = None):
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_record(
        self,
        *,
        item_name: str,
        unit_price: float,
        quantity: float = 1.0,
        unit: str = "개",
        category: str = "입고",
        report_date: str = "",
        source_file: str = "",
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        subtotal = round(quantity * unit_price, 2)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO item_history
                (created_at, report_date, category, item_name, norm_name, unit, quantity, unit_price, subtotal, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    report_date or now[:10],
                    category,
                    item_name.strip(),
                    normalize_name(item_name),
                    unit.strip() or "개",
                    float(quantity),
                    float(unit_price),
                    subtotal,
                    source_file,
                ),
            )

    def save_checked_items(
        self,
        items: list[CheckedItem],
        *,
        source_file: str = "",
        include_warnings: bool = False,
    ) -> int:
        """默认只把校验通过的行写入历史库，避免异常/手算错行污染均价基准。"""
        saved = 0
        for item in items:
            if not include_warnings and item.status != "OK":
                continue
            if item.quantity <= 0 or item.unit_price <= 0:
                continue
            self.add_record(
                item_name=item.item_name,
                unit_price=item.unit_price,
                quantity=item.quantity,
                unit=item.unit,
                category=item.category,
                report_date=item.report_date,
                source_file=source_file or item.page_label,
            )
            saved += 1
        return saved

    def get_price_stats(self, item_name: str, *, category: str | None = None) -> PriceStats | None:
        candidates = _candidate_names(item_name)
        if not candidates:
            return None
        with self._connect() as conn:
            for norm in candidates:
                params: list = [norm]
                cat_sql = ""
                if category:
                    cat_sql = " AND category = ?"
                    params.append(category)
                row = conn.execute(
                    f"""
                    SELECT
                        MAX(item_name) AS item_name,
                        AVG(unit_price) AS avg_price,
                        MIN(unit_price) AS min_price,
                        MAX(unit_price) AS max_price,
                        COUNT(*) AS cnt
                    FROM item_history
                    WHERE norm_name = ? AND unit_price > 0{cat_sql}
                    """,
                    params,
                ).fetchone()
                if not row or not row["cnt"]:
                    continue
                last_row = conn.execute(
                    f"SELECT unit_price FROM item_history WHERE norm_name = ?{cat_sql} ORDER BY id DESC LIMIT 1",
                    params,
                ).fetchone()
                unit_row = conn.execute(
                    f"""
                    SELECT unit, COUNT(*) AS c
                    FROM item_history
                    WHERE norm_name = ?{cat_sql}
                    GROUP BY unit
                    ORDER BY c DESC
                    LIMIT 1
                    """,
                    params,
                ).fetchone()
                return PriceStats(
                    item_name=row["item_name"],
                    avg_unit_price=round(float(row["avg_price"]), 2),
                    last_unit_price=float(last_row["unit_price"]),
                    min_unit_price=float(row["min_price"]),
                    max_unit_price=float(row["max_price"]),
                    common_unit=unit_row["unit"] if unit_row else "개",
                    sample_count=int(row["cnt"]),
                )
        return None

    def list_item_summaries(self, limit: int = 50) -> list[PriceStats]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    MAX(item_name) AS item_name,
                    norm_name,
                    AVG(unit_price) AS avg_price,
                    MIN(unit_price) AS min_price,
                    MAX(unit_price) AS max_price,
                    COUNT(*) AS cnt
                FROM item_history
                WHERE unit_price > 0
                GROUP BY norm_name
                ORDER BY cnt DESC, MAX(id) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            summaries: list[PriceStats] = []
            for r in rows:
                last_row = conn.execute(
                    "SELECT unit_price, unit FROM item_history WHERE norm_name = ? ORDER BY id DESC LIMIT 1",
                    (r["norm_name"],),
                ).fetchone()
                summaries.append(
                    PriceStats(
                        item_name=r["item_name"],
                        avg_unit_price=round(float(r["avg_price"]), 2),
                        last_unit_price=float(last_row["unit_price"]),
                        min_unit_price=float(r["min_price"]),
                        max_unit_price=float(r["max_price"]),
                        common_unit=last_row["unit"],
                        sample_count=int(r["cnt"]),
                    )
                )
            return summaries

    def build_prompt_context(self, limit: int = 40) -> str:
        """生成历史品项·单价参考表，注入 Prompt 辅助多模态模型区分数量与单价。"""
        items = self.list_item_summaries(limit=limit)
        if not items:
            return "(과거 품목 이력 없음)"
        lines = ["품목명 | 과거평균단가 | 기본단위 | 누적건수"]
        for s in items:
            lines.append(f"{s.item_name} | {s.avg_unit_price:g} | {s.common_unit} | {s.sample_count}건")
        return "\n".join(lines)

    def count_records(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM item_history").fetchone()
            return int(row["c"]) if row else 0

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM item_history")
