"""文档加载层：把图片、多页 PDF（PyMuPDF）或文件夹统一转为按页图像列表。"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = IMAGE_EXTS | PDF_EXTS


@dataclass
class PageImage:
    source_name: str
    page_label: str  # 例："1" 或 "report.pdf#2"
    png_bytes: bytes
    text_hint: str = ""  # PDF 若带文字层，作为辅助提示给多模态模型核对数字

    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png_bytes).decode("ascii")


def parse_pages(spec: str | None) -> list[int] | None:
    """把 "1-3,5" 解析成 [1, 2, 3, 5]（从 1 开始的页码）。"""
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start <= 0 or end < start:
                raise ValueError(f"无效页码范围：{part}")
            pages.update(range(start, end + 1))
        else:
            p = int(part)
            if p <= 0:
                raise ValueError(f"页码必须从 1 开始：{part}")
            pages.add(p)
    return sorted(pages)


def _load_image_bytes(path: Path, max_side: int = 2000) -> bytes:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        # 限制过大的手机原图边长，省 token 且不损清晰度
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _load_pdf_pages(path: Path, pages: list[int] | None = None, dpi: int = 200) -> list[PageImage]:
    import pymupdf

    result: list[PageImage] = []
    with pymupdf.open(path) as doc:
        total = len(doc)
        indices = [p - 1 for p in pages if 1 <= p <= total] if pages else list(range(total))
        for idx in indices:
            page = doc[idx]
            pix = page.get_pixmap(dpi=dpi)
            text_hint = page.get_text("text").strip()
            result.append(
                PageImage(
                    source_name=path.name,
                    page_label=f"{path.name}#P{idx + 1}",
                    png_bytes=pix.tobytes("png"),
                    text_hint=text_hint[:2000],  # 仅作辅助提示，避免过长
                )
            )
    return result


def load_inputs(paths: list[Path], *, pages: list[int] | None = None, dpi: int = 200) -> list[PageImage]:
    """加载一个或多个文件/目录，按顺序展开成按页图片列表。"""
    files: list[Path] = []
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"找不到输入路径：{p}")
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS))
        elif p.suffix.lower() in SUPPORTED_EXTS:
            files.append(p)
        else:
            raise ValueError(f"不支持的文件类型：{p.name}（支持 PDF 与常见图片格式）")

    if not files:
        raise ValueError("没有找到可处理的 PDF 或图片文件。")

    output: list[PageImage] = []
    for file in files:
        ext = file.suffix.lower()
        if ext in PDF_EXTS:
            output.extend(_load_pdf_pages(file, pages=pages, dpi=dpi))
        else:
            output.append(
                PageImage(
                    source_name=file.name,
                    page_label=file.name,
                    png_bytes=_load_image_bytes(file),
                )
            )
    return output
