"""核心数据模型：单据抽取结果与 Python 独立校验结果。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    """多模态模型从单据上抽取的单条明细（原样记录单据上的数字，交给 Python 验算）。"""

    category: str = Field(default="입고", description="类别，如 매출 / 입고 / 지출 / 기타")
    item_name: str = Field(..., min_length=1, description="品名")
    quantity: float = Field(..., description="数量")
    unit: str = Field(default="개", description="单位，如 kg / 박스 / 개 / 병")
    unit_price: float = Field(..., description="单价")
    reported_subtotal: float | None = Field(default=None, description="单据上写的小计金额（无则 null）")
    note: str = Field(default="", description="备注")


class ExtractedPage(BaseModel):
    """单页单据的结构化识别结果。"""

    report_date: str = Field(default="", description="单据日期，建议 YYYY-MM-DD")
    store_or_vendor: str = Field(default="", description="店名或供应商名")
    currency: str = Field(default="KRW", description="币种，如 KRW / CNY / USD")
    reported_total: float | None = Field(default=None, description="单据底部标注的总计金额（无则 null）")
    items: list[LineItem] = Field(default_factory=list)


@dataclass
class CheckedItem:
    """经过 Python 独立验算和历史均价对比后的单行结果。"""

    page_label: str
    report_date: str
    store_or_vendor: str
    category: str
    item_name: str
    quantity: float
    unit: str
    unit_price: float
    computed_subtotal: float
    reported_subtotal: float | None
    subtotal_diff: float | None
    history_avg_price: float | None
    history_samples: int
    price_deviation: float | None  # (unit_price - history_avg_price) / history_avg_price
    status: str  # "OK" | "WARN"
    warning_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class PageCheckResult:
    """单页校验汇总。"""

    source_name: str
    page_label: str
    report_date: str
    store_or_vendor: str
    currency: str
    items: list[CheckedItem]
    computed_total: float
    reported_total: float | None
    total_diff: float | None
    total_mismatch: bool
    page_warnings: list[str] = field(default_factory=list)
    error: str = ""  # 若该页抽取失败记录原因，不拖垮其他页
    prompt_tokens: int = 0
    completion_tokens: int = 0
