"""后台识别与验算线程：不阻塞主界面，逐页回报进度并支持取消。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..config import Settings, ValidationSettings
from ..demo import DemoMockLLM
from ..extractor import PageExtractOutcome, extract_page
from ..history import HistoryStore
from ..ingest import PageImage, load_inputs, parse_pages
from ..llm import FatalLLMError, LLMClient, Usage
from ..models import PageCheckResult
from ..validator import validate_page


class ConvertWorker(QThread):
    # done, total, label, ok, message
    page_progress = Signal(int, int, str, bool, str)
    stage_changed = Signal(str)
    # results, page_images_by_label, elapsed, usage
    completed = Signal(object, object, float, object)
    failed = Signal(str)

    def __init__(
        self,
        inputs: list[Path],
        settings: Settings,
        history: HistoryStore,
        *,
        pages_spec: str = "",
        threshold: float = 0.35,
        mock_mode: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.inputs = inputs
        self.settings = settings
        self.history = history
        self.pages_spec = pages_spec
        self.threshold = threshold
        self.mock_mode = mock_mode
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            self.stage_changed.emit("正在加载图片与 PDF 页面...")
            pages_filter = parse_pages(self.pages_spec.strip() or None)
            pages = load_inputs(self.inputs, pages=pages_filter, dpi=self.settings.dpi)
            if self._cancelled:
                self.failed.emit("已取消")
                return

            page_images: dict[str, bytes] = {p.page_label: p.png_bytes for p in pages}
            history_ctx = self.history.build_prompt_context()
            llm = DemoMockLLM() if self.mock_mode else LLMClient.from_settings(self.settings.llm)

            self.stage_changed.emit(f"正在并发识别 {len(pages)} 页单据（模型: {'离线演示' if self.mock_mode else self.settings.llm.model}）...")
            workers = 1 if self.mock_mode else max(1, min(self.settings.max_workers, len(pages)))
            outcomes: list[PageExtractOutcome | None] = [None] * len(pages)
            done = 0

            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {
                    pool.submit(extract_page, page, llm, history_ctx): idx
                    for idx, page in enumerate(pages)
                }
                for future in as_completed(future_map):
                    if self._cancelled:
                        pool.shutdown(wait=False, cancel_futures=True)
                        self.failed.emit("用户已取消任务")
                        return
                    idx = future_map[future]
                    outcome = future.result()  # FatalLLMError 立即向上抛出
                    outcomes[idx] = outcome
                    done += 1
                    ok = outcome.extracted is not None
                    msg = f"识别到 {len(outcome.extracted.items)} 条明细" if ok else outcome.error
                    self.page_progress.emit(done, len(pages), outcome.page.page_label, ok, msg)

            self.stage_changed.emit("正在运行 Python 独立算术与历史单价校验...")
            val_cfg = ValidationSettings(
                price_deviation_limit=self.threshold,
                math_tolerance=self.settings.validation.math_tolerance,
                min_history_samples=self.settings.validation.min_history_samples,
            )
            total_usage = Usage()
            results: list[PageCheckResult] = []
            for outcome in outcomes:
                if outcome is None:
                    continue
                total_usage.add(outcome.usage)
                if outcome.extracted is None:
                    results.append(
                        PageCheckResult(
                            source_name=outcome.page.source_name,
                            page_label=outcome.page.page_label,
                            report_date="",
                            store_or_vendor="",
                            currency="",
                            items=[],
                            computed_total=0.0,
                            reported_total=None,
                            total_diff=None,
                            total_mismatch=False,
                            error=outcome.error,
                            prompt_tokens=outcome.usage.prompt_tokens,
                            completion_tokens=outcome.usage.completion_tokens,
                        )
                    )
                    continue
                checked = validate_page(
                    outcome.extracted,
                    source_name=outcome.page.source_name,
                    page_label=outcome.page.page_label,
                    history=self.history,
                    settings=val_cfg,
                    prompt_tokens=outcome.usage.prompt_tokens,
                    completion_tokens=outcome.usage.completion_tokens,
                )
                results.append(checked)

            elapsed = time.perf_counter() - t0
            self.completed.emit(results, page_images, elapsed, total_usage)
        except FatalLLMError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"处理失败：{exc}")
