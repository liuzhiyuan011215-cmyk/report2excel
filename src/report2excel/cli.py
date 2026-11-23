"""终端命令行入口（仿 CardMaker cli.py，核心逻辑与后续 PySide6 GUI 完全分离）。

示例：
  report2excel demo                                      # 免 Key 一键演示完整流程
  report2excel config preset gemini                      # 切换多模态模型预设
  report2excel config set-key                            # 安全粘贴 API Key
  report2excel config test                               # 测试模型连通性
  report2excel convert report.pdf -o out.xlsx            # 识别 + 校验 + 生成公式 Excel
  report2excel convert ./photos/ --save-history          # 批量转换并将正常行入历史库
  report2excel history list                              # 查看 SQLite 历史品项与均价
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import (
    LLM_PRESETS,
    clean_pasted_key,
    config_path,
    db_path,
    load_settings,
    mask_key,
    save_settings,
)
from .demo import DemoMockLLM, generate_sample_report, seed_demo_history
from .excel_export import export_excel
from .extractor import extract_pages
from .history import HistoryStore
from .ingest import load_inputs, parse_pages
from .llm import FatalLLMError, LLMClient, Usage, check_connection, explain_error
from .models import PageCheckResult
from .validator import validate_page

# 终端 ANSI 颜色（非 TTY 时自动关闭）
USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def _fmt_num(val: float | None) -> str:
    if val is None:
        return "-"
    return f"{int(val):,}" if float(val).is_integer() else f"{val:,.2f}"


def _print_summary_table(results: list[PageCheckResult], elapsed: float, usage: Usage) -> None:
    print()
    print(_c("═" * 88, "36"))
    print(_c("  Report2Excel 校验结果预览（Python 独立验算 · 问题行将在 Excel 中标黄）", "1;36"))
    print(_c("═" * 88, "36"))

    total_items = 0
    warn_items = 0
    for page in results:
        print(
            f"\n▶ 页面: {_c(page.page_label, '1')}  | 日期: {page.report_date or '-'}  "
            f"| 店名/供应商: {page.store_or_vendor or '-'}"
        )
        if page.error:
            print(_c(f"  [失败] {page.error}", "31"))
            continue

        print(
            f"  {'状态':<4} {'品名':<12} {'数量':>6} {'单价':>8} "
            f"{'Python小计':>10} {'原单小计':>10} {'历史均价':>9}  说明"
        )
        print("  " + "-" * 84)
        for item in page.items:
            total_items += 1
            is_warn = item.status == "WARN"
            if is_warn:
                warn_items += 1
            badge = _c("WARN", "1;33") if is_warn else _c(" OK ", "32")
            hist_str = _fmt_num(item.history_avg_price)
            note = " / ".join(item.warnings) if item.warnings else (item.note or "-")
            if is_warn:
                note = _c(note, "33")
            print(
                f"  {badge} {item.item_name:<12} {_fmt_num(item.quantity):>6} {_fmt_num(item.unit_price):>8} "
                f"{_fmt_num(item.computed_subtotal):>10} {_fmt_num(item.reported_subtotal):>10} "
                f"{hist_str:>9}  {note}"
            )

        print("  " + "-" * 84)
        total_line = (
            f"  合计核对: Python重算={_fmt_num(page.computed_total)}  "
            f"原单合计={_fmt_num(page.reported_total)}"
        )
        if page.total_mismatch:
            print(_c(total_line + f"  ⚠ 差额={_fmt_num(page.total_diff)}", "1;33"))
        else:
            print(_c(total_line + "  ✓ 一致", "32"))

    print()
    print(
        f"统计: 共 {len(results)} 页 / {total_items} 条明细 | "
        f"正常 {total_items - warn_items} 条 | "
        f"{_c(f'警告 {warn_items} 条(已标黄)', '1;33') if warn_items else _c('警告 0 条', '32')} | "
        f"耗时 {elapsed:.2f}s | Token {usage.prompt_tokens}+{usage.completion_tokens}"
    )


# ---------------------------------------------------------------- config
def cmd_config(args) -> int:
    settings = load_settings()
    if args.action == "path":
        print(f"配置文件: {config_path()}")
        print(f"历史库:   {db_path()}")
    elif args.action == "show":
        data = settings.model_dump()
        data["llm"]["api_key"] = mask_key(settings.llm.api_key)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"\n配置文件: {config_path()}")
    elif args.action == "preset":
        if not args.value or args.value not in LLM_PRESETS:
            print(f"可选预设: {', '.join(LLM_PRESETS)}")
            return 1
        settings.llm.apply_preset(args.value)
        save_settings(settings)
        print(f"已切换到 {args.value}: {settings.llm.base_url}  模型 {settings.llm.model}")
    elif args.action == "set-key":
        raw = getpass.getpass("请粘贴 API Key（屏幕不回显），回车确认: ")
        key, note = clean_pasted_key(raw)
        if not key:
            print("未输入内容，已取消。")
            return 1
        settings.llm.api_key = key
        path = save_settings(settings)
        print(f"已保存 {mask_key(key)}（{len(key)} 位）到 {path}")
        if note:
            print(note)
    elif args.action == "set-model":
        if not args.value:
            print("请提供模型名称，例如: report2excel config set-model qwen-vl-plus")
            return 1
        settings.llm.model = args.value
        save_settings(settings)
        print(f"已将模型改为 {settings.llm.model}")
    elif args.action == "test":
        if not settings.llm.ready:
            print("尚未配置 API Key，请先运行: report2excel config set-key")
            return 1
        try:
            print(check_connection(settings.llm))
        except Exception as exc:
            print(f"连接失败: {exc if isinstance(exc, FatalLLMError) else explain_error(exc)}")
            return 1
    return 0


# ---------------------------------------------------------------- history
def cmd_history(args) -> int:
    store = HistoryStore()
    if args.action == "list":
        rows = store.list_item_summaries(limit=args.limit)
        if not rows:
            print("历史品项库为空。可运行 `report2excel history seed-demo` 写入测试数据，或在转换时加 `--save-history`。")
            return 0
        print(f"历史库位置: {store.path}（总记录 {store.count_records()} 条，去重品项 {len(rows)} 种）\n")
        print(f"{'品名':<16} {'平均单价':>10} {'最近单价':>10} {'最低~最高':>18} {'单位':>6} {'样本数':>6}")
        print("-" * 74)
        for s in rows:
            rng = f"{_fmt_num(s.min_unit_price)}~{_fmt_num(s.max_unit_price)}"
            print(
                f"{s.item_name:<16} {_fmt_num(s.avg_unit_price):>10} {_fmt_num(s.last_unit_price):>10} "
                f"{rng:>18} {s.common_unit:>6} {s.sample_count:>6}"
            )
    elif args.action == "seed-demo":
        n = seed_demo_history(store)
        print(f"已写入 {n} 条演示历史采购记录到 {store.path}")
    elif args.action == "clear":
        store.clear()
        print(f"已清空历史库: {store.path}")
    return 0


# ---------------------------------------------------------------- convert
def _run_pipeline(
    inputs: list[Path],
    *,
    output_path: Path,
    llm,
    history: HistoryStore,
    pages_spec: str | None = None,
    dpi: int = 200,
    max_workers: int = 3,
    threshold: float = 0.35,
    save_history: bool = False,
) -> tuple[list[PageCheckResult], Path, float, Usage]:
    settings = load_settings()
    settings.validation.price_deviation_limit = threshold

    t0 = time.perf_counter()
    page_list = parse_pages(pages_spec)
    pages = load_inputs(inputs, pages=page_list, dpi=dpi)
    print(f"已加载 {len(pages)} 页单据，开始多模态识别...")

    history_ctx = history.build_prompt_context()

    def _progress(done: int, total: int, outcome) -> None:
        mark = "✓" if outcome.extracted else "✗"
        print(f"  [{done}/{total}] {mark} {outcome.page.page_label}", file=sys.stderr)

    outcomes = extract_pages(
        pages,
        llm,
        history_ctx,
        max_workers=max_workers,
        on_progress=_progress,
    )

    total_usage = Usage()
    results: list[PageCheckResult] = []
    for outcome in outcomes:
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
            history=history,
            settings=settings.validation,
            prompt_tokens=outcome.usage.prompt_tokens,
            completion_tokens=outcome.usage.completion_tokens,
        )
        results.append(checked)

    export_excel(results, output_path)

    if save_history:
        saved = sum(
            history.save_checked_items(page.items, source_file=page.source_name)
            for page in results
        )
        print(f"已将 {saved} 条校验通过的品项写入历史库（异常行未入库，避免污染均价）。")

    elapsed = time.perf_counter() - t0
    return results, output_path, elapsed, total_usage


def cmd_convert(args) -> int:
    settings = load_settings()
    if not settings.llm.ready:
        print("尚未配置 API Key。请先运行:")
        print("  report2excel config preset gemini   # 或 dashscope / openai / claude / ollama")
        print("  report2excel config set-key")
        print("如果想免 Key 直接体验全流程，请运行: report2excel demo")
        return 1

    inputs = [Path(p) for p in args.inputs]
    if args.out:
        out_path = Path(args.out)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = inputs[0].stem if len(inputs) == 1 else "batch"
        out_path = Path("output") / f"{stem}_{ts}.xlsx"

    llm = LLMClient.from_settings(settings.llm)
    history = HistoryStore()
    try:
        results, excel_path, elapsed, usage = _run_pipeline(
            inputs,
            output_path=out_path,
            llm=llm,
            history=history,
            pages_spec=args.pages,
            dpi=args.dpi or settings.dpi,
            max_workers=args.workers or settings.max_workers,
            threshold=args.threshold,
            save_history=args.save_history,
        )
    except FatalLLMError as exc:
        print(f"致命错误，任务已停止: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"处理失败: {exc}", file=sys.stderr)
        return 1

    _print_summary_table(results, elapsed, usage)
    print(_c(f"\n✓ 已生成 Excel 文件: {excel_path.resolve()}", "1;32"))
    return 0


# ---------------------------------------------------------------- demo
def cmd_demo(args) -> int:
    demo_dir = Path(args.dir)
    samples_dir = demo_dir / "samples"
    png_path, pdf_path = generate_sample_report(samples_dir)
    target = pdf_path if args.pdf else png_path

    # 演示使用独立 SQLite，不污染用户正式历史库
    demo_db = demo_dir / "demo_history.sqlite3"
    history = HistoryStore(demo_db)
    history.clear()
    seed_demo_history(history)

    if args.real:
        settings = load_settings()
        if not settings.llm.ready:
            print("使用 --real 需要先配置 API Key：report2excel config set-key")
            return 1
        llm = LLMClient.from_settings(settings.llm)
        print(f"使用真实多模态模型 ({settings.llm.model}) 识别演示样本: {target}")
    else:
        llm = DemoMockLLM()
        print(f"离线演示模式（免 API Key）| 输入样本: {target}")

    out_path = demo_dir / "demo_output.xlsx"
    results, excel_path, elapsed, usage = _run_pipeline(
        [target],
        output_path=out_path,
        llm=llm,
        history=history,
        max_workers=1,
        threshold=0.35,
        save_history=False,
    )
    _print_summary_table(results, elapsed, usage)
    print(_c(f"\n✓ 演示样本图片: {png_path.resolve()}", "36"))
    print(_c(f"✓ 演示样本 PDF: {pdf_path.resolve()}", "36"))
    print(_c(f"✓ 演示导出 Excel: {excel_path.resolve()}", "1;32"))
    return 0


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report2excel",
        description="图片 / PDF 营业报告 → 带公式与自动校验的 Excel 转换工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # config
    p_cfg = sub.add_parser("config", help="查看或配置多模态大模型与 API Key")
    p_cfg.add_argument("action", choices=["show", "path", "preset", "set-key", "set-model", "test"])
    p_cfg.add_argument("value", nargs="?", help="preset 名称或模型名")
    p_cfg.set_defaults(func=cmd_config)

    # history
    p_hist = sub.add_parser("history", help="管理 SQLite 历史品项·单价库")
    p_hist.add_argument("action", choices=["list", "seed-demo", "clear"])
    p_hist.add_argument("--limit", type=int, default=50)
    p_hist.set_defaults(func=cmd_history)

    # convert
    p_conv = sub.add_parser("convert", help="将图片 / PDF / 文件夹转为带公式和自动校验的 Excel")
    p_conv.add_argument("inputs", nargs="+", help="一个或多个图片、PDF 文件或目录")
    p_conv.add_argument("-o", "--out", help="输出 .xlsx 路径（默认 output/<文件名>_<时间>.xlsx）")
    p_conv.add_argument("--pages", help="PDF 页码范围，例如 1-3,5")
    p_conv.add_argument("--threshold", type=float, default=0.35, help="历史单价波动报警阈值（默认 0.35 即 ±35%%）")
    p_conv.add_argument("--dpi", type=int, default=0, help="PDF 渲染 DPI（默认读取配置 200）")
    p_conv.add_argument("--workers", type=int, default=0, help="并发页数（默认读取配置 3）")
    p_conv.add_argument("--save-history", action="store_true", help="将本次校验通过的行存入 SQLite 历史库")
    p_conv.set_defaults(func=cmd_convert)

    # demo
    p_demo = sub.add_parser("demo", help="生成仿真单据并一键运行全流程演示（默认免 API Key）")
    p_demo.add_argument("--dir", default="output/demo", help="演示文件输出目录")
    p_demo.add_argument("--pdf", action="store_true", help="以生成的 PDF 作为输入（默认用 PNG 图片）")
    p_demo.add_argument("--real", action="store_true", help="调用已配置的真实多模态 LLM 识别演示样本")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
