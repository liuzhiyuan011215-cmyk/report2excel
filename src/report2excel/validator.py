"""Python 独立校验引擎：不依赖 AI 算术，用 Python 重新核对数量×单价、总计以及 ±35% 历史单价波动。"""
from __future__ import annotations

from .config import ValidationSettings
from .history import HistoryStore
from .models import CheckedItem, ExtractedPage, PageCheckResult


def _fmt_num(val: float) -> str:
    return f"{int(val):,}" if float(val).is_integer() else f"{val:,.2f}"


def validate_page(
    extracted: ExtractedPage,
    *,
    source_name: str,
    page_label: str,
    history: HistoryStore | None = None,
    settings: ValidationSettings | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> PageCheckResult:
    cfg = settings or ValidationSettings()
    checked_items: list[CheckedItem] = []

    for item in extracted.items:
        warning_codes: list[str] = []
        warnings: list[str] = []

        if item.quantity <= 0 or item.unit_price <= 0:
            warning_codes.append("INVALID_VALUE")
            warnings.append(
                f"수량/단가 이상(수량 {_fmt_num(item.quantity)}, 단가 {_fmt_num(item.unit_price)})"
            )

        computed = round(item.quantity * item.unit_price, 2)
        diff: float | None = None
        if item.reported_subtotal is not None:
            diff = round(computed - item.reported_subtotal, 2)
            if abs(diff) > cfg.math_tolerance:
                warning_codes.append("MATH_ERROR")
                sign = "+" if diff > 0 else ""
                warnings.append(
                    f"계산 오류: {_fmt_num(item.quantity)}×{_fmt_num(item.unit_price)}={_fmt_num(computed)} "
                    f"(원본 {_fmt_num(item.reported_subtotal)}, 차이 {sign}{_fmt_num(diff)})"
                )

        hist_avg: float | None = None
        hist_samples = 0
        deviation: float | None = None
        if history is not None:
            stats = history.get_price_stats(item.item_name, category=item.category)
            if stats and stats.sample_count >= cfg.min_history_samples and stats.avg_unit_price > 0:
                hist_avg = stats.avg_unit_price
                hist_samples = stats.sample_count
                deviation = (item.unit_price - hist_avg) / hist_avg
                if abs(deviation) > cfg.price_deviation_limit:
                    warning_codes.append("PRICE_SPIKE")
                    pct_limit = int(round(cfg.price_deviation_limit * 100))
                    warnings.append(
                        f"단가 급변 {deviation:+.1%} "
                        f"(과거 평균 {_fmt_num(hist_avg)} → 현재 {_fmt_num(item.unit_price)}, ±{pct_limit}% 초과)"
                    )

        checked_items.append(
            CheckedItem(
                page_label=page_label,
                report_date=extracted.report_date,
                store_or_vendor=extracted.store_or_vendor,
                category=item.category,
                item_name=item.item_name,
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                computed_subtotal=computed,
                reported_subtotal=item.reported_subtotal,
                subtotal_diff=diff,
                history_avg_price=hist_avg,
                history_samples=hist_samples,
                price_deviation=deviation,
                status="WARN" if warning_codes else "OK",
                warning_codes=warning_codes,
                warnings=warnings,
                note=item.note,
            )
        )

    computed_total = round(sum(i.computed_subtotal for i in checked_items), 2)
    total_diff: float | None = None
    total_mismatch = False
    page_warnings: list[str] = []

    if extracted.reported_total is not None:
        total_diff = round(computed_total - extracted.reported_total, 2)
        if abs(total_diff) > cfg.math_tolerance:
            total_mismatch = True
            sign = "+" if total_diff > 0 else ""
            page_warnings.append(
                f"합계 불일치: Python 재계산 {_fmt_num(computed_total)} ≠ "
                f"원본 합계 {_fmt_num(extracted.reported_total)} (차이 {sign}{_fmt_num(total_diff)})"
            )

    return PageCheckResult(
        source_name=source_name,
        page_label=page_label,
        report_date=extracted.report_date,
        store_or_vendor=extracted.store_or_vendor,
        currency=extracted.currency,
        items=checked_items,
        computed_total=computed_total,
        reported_total=extracted.reported_total,
        total_diff=total_diff,
        total_mismatch=total_mismatch,
        page_warnings=page_warnings,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
