"""内置演示与样本生成：复现简历中的手算错误(4×115→450)与 ±35% 单价波动标黄检测。"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .history import HistoryStore
from .llm import Usage

# 历史基线数据（模拟食堂过去几天的采购记录）
DEMO_HISTORY_RECORDS = [
    ("2026-11-18", "입고", "삼겹살", "kg", 12, 18200),
    ("2026-11-20", "입고", "삼겹살", "kg", 10, 18600),
    ("2026-11-19", "입고", "배추김치", "박스", 4, 24000),
    ("2026-11-21", "입고", "배추김치", "박스", 6, 23600),
    ("2026-11-18", "입고", "식용유(대)", "통", 4, 115),
    ("2026-11-20", "입고", "식용유(대)", "통", 5, 115),
    ("2026-11-18", "입고", "대파", "단", 10, 3700),
    ("2026-11-21", "입고", "대파", "단", 8, 3900),
    ("2026-11-20", "입고", "쌀(20kg)", "포", 3, 52000),
    ("2026-11-19", "입고", "두부", "모", 10, 1800),
    ("2026-11-20", "입고", "청양고추", "kg", 3, 4500),
    ("2026-11-20", "입고", "양파(망)", "망", 5, 8000),
    ("2026-11-20", "입고", "양파", "망", 5, 8000),
    ("2026-11-20", "입고", "계란(특란)", "판", 4, 7500),
    ("2026-11-20", "입고", "마늘", "kg", 3, 9500),
]

# 演示单据明细（含 1 条手算错误 4×115=450，1 条单价暴涨 +63.2%）
DEMO_REPORT_DATA = {
    "report_date": "2026-11-23",
    "store_or_vendor": "한빛식당 · 중앙식자재마트",
    "currency": "KRW",
    "reported_total": 459050,
    "items": [
        {
            "category": "입고",
            "item_name": "삼겹살",
            "quantity": 10,
            "unit": "kg",
            "unit_price": 18500,
            "reported_subtotal": 185000,
            "note": "정상 입고",
        },
        {
            "category": "입고",
            "item_name": "배추김치",
            "quantity": 5,
            "unit": "박스",
            "unit_price": 24000,
            "reported_subtotal": 120000,
            "note": "",
        },
        {
            "category": "입고",
            "item_name": "식용유(대)",
            "quantity": 4,
            "unit": "통",
            "unit_price": 115,
            "reported_subtotal": 450,  # 经典手算错误：4×115 应为 460
            "note": "수기 전표",
        },
        {
            "category": "입고",
            "item_name": "대파",
            "quantity": 8,
            "unit": "단",
            "unit_price": 6200,  # 历史均价 3800 → +63.2%，超过 ±35%
            "reported_subtotal": 49600,
            "note": "산지 시세 급등",
        },
        {
            "category": "입고",
            "item_name": "쌀(20kg)",
            "quantity": 2,
            "unit": "포",
            "unit_price": 52000,
            "reported_subtotal": 104000,
            "note": "",
        },
    ],
}


def seed_demo_history(store: HistoryStore) -> int:
    for report_date, category, name, unit, qty, price in DEMO_HISTORY_RECORDS:
        store.add_record(
            report_date=report_date,
            category=category,
            item_name=name,
            unit=unit,
            quantity=qty,
            unit_price=price,
            source_file="seed_demo",
        )
    return len(DEMO_HISTORY_RECORDS)


def _load_cjk_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def generate_sample_report(output_dir: Path) -> tuple[Path, Path]:
    """生成一份真实的仿真营业报告 PNG 和一份 PDF，便于本地演示与真机识别测试。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / "sample_daily_report.png"
    pdf_path = output_dir / "sample_daily_report.pdf"

    img = Image.new("RGB", (980, 680), color=(252, 252, 250))
    draw = ImageDraw.Draw(img)
    title_font = _load_cjk_font(28)
    sub_font = _load_cjk_font(18)
    body_font = _load_cjk_font(19)

    draw.rectangle([(36, 30), (944, 645)], outline=(45, 55, 72), width=2)
    draw.text((64, 52), "일일 입고 · 영업 보고서 (테스트 샘플)", fill=(20, 30, 50), font=title_font)
    draw.text(
        (64, 96),
        f"날짜: {DEMO_REPORT_DATA['report_date']}    거래처/매장: {DEMO_REPORT_DATA['store_or_vendor']}",
        fill=(70, 80, 95),
        font=sub_font,
    )

    # 表头
    y = 148
    draw.rectangle([(56, y), (924, y + 42)], fill=(30, 58, 95))
    cols = [(72, "구분"), (160, "품목명"), (365, "수량"), (450, "단위"), (535, "단가"), (665, "소계(기재)"), (800, "비고")]
    for x, label in cols:
        draw.text((x, y + 10), label, fill=(255, 255, 255), font=sub_font)

    y += 50
    for idx, item in enumerate(DEMO_REPORT_DATA["items"]):
        if idx % 2 == 1:
            draw.rectangle([(56, y - 4), (924, y + 42)], fill=(241, 245, 249))
        draw.line([(56, y + 42), (924, y + 42)], fill=(203, 213, 225), width=1)
        row_cells = [
            (72, item["category"]),
            (160, item["item_name"]),
            (375, str(item["quantity"])),
            (454, item["unit"]),
            (540, f"{item['unit_price']:,}"),
            (675, f"{item['reported_subtotal']:,}"),
            (800, item["note"]),
        ]
        for x, text in row_cells:
            draw.text((x, y + 8), text, fill=(30, 41, 59), font=body_font)
        y += 48

    # 底部手写合计（沿用原单错算后的 459,050）
    y += 18
    draw.rectangle([(56, y), (924, y + 48)], fill=(226, 232, 240))
    draw.text((72, y + 12), "기재 총합계 (원본 수기 합산):", fill=(15, 23, 42), font=body_font)
    draw.text((710, y + 12), f"{DEMO_REPORT_DATA['reported_total']:,} 원", fill=(15, 23, 42), font=body_font)

    draw.text(
        (64, 595),
        "※ 검증 포인트: 식용유(대) 4×115=460인데 450으로 오기 / 대파 단가 과거 평균(3,800) 대비 +63.2%",
        fill=(140, 50, 20),
        font=sub_font,
    )
    img.save(png_path, format="PNG")

    # 用 PyMuPDF 把图片封装成单页 PDF，同时验证 PDF 路径
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=img.width, height=img.height)
    page.insert_image(page.rect, filename=str(png_path))
    doc.save(pdf_path)
    doc.close()

    return png_path, pdf_path


class DemoMockLLM:
    """演示与离线测试用模拟多模态模型：返回仿真样本的结构化 JSON。"""

    def chat(self, messages: list[dict]) -> tuple[str, Usage]:
        return json.dumps(DEMO_REPORT_DATA, ensure_ascii=False), Usage(
            prompt_tokens=620,
            completion_tokens=210,
            calls=1,
        )
