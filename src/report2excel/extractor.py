"""多模态 LLM 按页抽取：结合历史品项单价表区分数量与单价，并严格做 Pydantic 校验与重试。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from pydantic import ValidationError

from .ingest import PageImage
from .llm import ChatModel, FatalLLMError, Usage, parse_json_object
from .models import ExtractedPage

SYSTEM_PROMPT = """\
너는 식당·매장의 일일 영업 보고서, 입고 전표, 영수증, 거래명세서 이미지에서 품목 데이터를 정확하게 추출하는 도우미다.

핵심 규칙:
1. 반드시 JSON 객체 하나만 출력한다(설명·마크다운 금지).
2. 수량(quantity)과 단가(unit_price)를 절대 혼동하지 않는다. 제공되는 [과거 품목·단가 이력]을 참고해 어느 숫자가 단가이고 어느 숫자가 수량인지 정확히 구분하라.
3. 원본 문서에 적힌 소계(reported_subtotal)와 총합계(reported_total)는 **절대 직접 고쳐 계산하지 말고, 문서에 적힌 숫자 그대로** 기록하라. 손계산 오류 검출은 후속 Python 프로그램이 수행한다.
4. 숫자는 쉼표(,)나 통화 기호(₩, 원, ¥, 元)를 제거한 순수 숫자로 출력한다.
5. 카테고리(category)는 문서 성격에 맞게 "입고", "매출", "지출", "기타" 중 하나로 통일한다.
"""

USER_PROMPT_TEMPLATE = """\
아래 이미지(페이지: {page_label})에서 일일 보고서/입고 내역을 추출해 다음 JSON 형식으로 출력하라.

[출력 JSON 스키마]
{{
  "report_date": "YYYY-MM-DD (연도가 없으면 MM-DD, 날짜 자체가 없으면 빈 문자열)",
  "store_or_vendor": "매장명 또는 거래처명 (없으면 빈 문자열)",
  "currency": "KRW 또는 CNY 등",
  "reported_total": 12345 또는 null,
  "items": [
    {{
      "category": "입고 | 매출 | 지출 | 기타",
      "item_name": "품목명",
      "quantity": 4,
      "unit": "개/kg/박스 등",
      "unit_price": 115,
      "reported_subtotal": 450,
      "note": "비고 (없으면 빈 문자열)"
    }}
  ]
}}

[과거 품목·단가 이력 (수량과 단가 구분 참고용)]
{history_context}
{text_hint_block}
"""


@dataclass
class PageExtractOutcome:
    page: PageImage
    extracted: ExtractedPage | None
    usage: Usage
    error: str = ""


def _build_messages(page: PageImage, history_context: str) -> list[dict]:
    hint_block = ""
    if page.text_hint:
        hint_block = f"\n[PDF 내장 텍스트 참고(레이아웃이 깨질 수 있으니 이미지 우선)]\n{page.text_hint}\n"
    user_text = USER_PROMPT_TEMPLATE.format(
        page_label=page.page_label,
        history_context=history_context,
        text_hint_block=hint_block,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": page.data_url()}},
            ],
        },
    ]


def extract_page(
    page: PageImage,
    llm: ChatModel,
    history_context: str,
    *,
    max_attempts: int = 3,
    retry_base_delay: float = 2.0,
) -> PageExtractOutcome:
    messages = _build_messages(page, history_context)
    total_usage = Usage()
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        try:
            raw, usage = llm.chat(messages)
            total_usage.add(usage)
            data = parse_json_object(raw)
            extracted = ExtractedPage.model_validate(data)
            return PageExtractOutcome(page=page, extracted=extracted, usage=total_usage)
        except FatalLLMError:
            raise
        except (ValueError, ValidationError) as exc:
            last_error = f"JSON/스키마 검증 실패: {exc}"
            # 输出格式不合格时，把具体错误反馈给模型让它原地修正
            messages = list(messages) + [
                {"role": "assistant", "content": raw if "raw" in locals() else ""},
                {
                    "role": "user",
                    "content": f"이전 응답이 스키마 검증에 실패했습니다({exc}). 올바른 JSON 객체 하나만 다시 출력하세요.",
                },
            ]
        except Exception as exc:
            last_error = f"호출 오류: {exc}"
            if attempt < max_attempts:
                time.sleep(retry_base_delay * (2 ** (attempt - 1)))

    return PageExtractOutcome(page=page, extracted=None, usage=total_usage, error=last_error)


def extract_pages(
    pages: list[PageImage],
    llm: ChatModel,
    history_context: str,
    *,
    max_workers: int = 3,
    on_progress: Callable[[int, int, PageExtractOutcome], None] | None = None,
) -> list[PageExtractOutcome]:
    """按页并发抽取，最终按原输入顺序返回；遇到 FatalLLMError 立即抛出。"""
    if not pages:
        return []

    workers = max(1, min(max_workers, len(pages)))
    outcomes: list[PageExtractOutcome | None] = [None] * len(pages)
    done = 0

    if workers == 1:
        for idx, page in enumerate(pages):
            outcome = extract_page(page, llm, history_context)
            outcomes[idx] = outcome
            done += 1
            if on_progress:
                on_progress(done, len(pages), outcome)
        return [o for o in outcomes if o is not None]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(extract_page, page, llm, history_context): idx
            for idx, page in enumerate(pages)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            outcome = future.result()  # 若为 FatalLLMError 会在这里抛出并终止
            outcomes[idx] = outcome
            done += 1
            if on_progress:
                on_progress(done, len(pages), outcome)

    return [o for o in outcomes if o is not None]
