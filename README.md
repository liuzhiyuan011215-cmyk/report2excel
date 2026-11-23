# Report2Excel：图片 / PDF 营业报告 → 带公式与自动校验的 Excel

把餐厅/门店每日营业报告、进货单（截图、照片、多页 PDF）自动整理为带公式的 Excel：
按页解析（PyMuPDF / Pillow）→ 注入 SQLite 历史品项·单价上下文 → 多模态 LLM 抽取结构化明细 → **Python 独立重算与历史单价 ±35% 校验** → 导出带 Excel 公式、**仅问题行标黄**的 `.xlsx`。

> 架构仿照 `CardMaker`，核心引擎与界面完全解耦：先完成终端 CLI 版本，后续可直接叠加 `PySide6` 桌面端。

## 快速安装与打开桌面 App

```bash
cd "/Users/wangyanan/vs code/pdf 转 Excel"
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/make_mac_launcher.py   # 生成可双击打开的 Report2Excel.app
```

安装好后，macOS 直接双击 **`Report2Excel.app`**，或终端运行 `.venv/bin/report2excel-gui` 即可打开桌面界面（右上角「设置」支持 `local-hydrogen`、`local-flash`、`gemini`、`dashscope`、`openai`、`claude`、`ollama` 一键预设）。

## 1. 一键离线演示（无需 API Key）

复现简历中的经典测试场景：
- 手算错误检出：`식용유(대)` `4 × 115 = 460`，原单据错写成 `450` → 自动检出并标黄
- 历史单价波动报警：`대파` 历史均价 `3,800`，本次 `6,200`（`+63.2%`，超过 `±35%`）→ 自动标黄

```bash
.venv/bin/report2excel demo          # 图片输入演示
.venv/bin/report2excel demo --pdf    # PDF 输入演示
```

## 2. 使用真实多模态模型

配置与 API Key 保存在用户数据目录（macOS：`~/Library/Application Support/Report2Excel/config.yaml`），不会提交进 git。

```bash
.venv/bin/report2excel config preset gemini      # 也支持 dashscope / openai / claude / ollama
.venv/bin/report2excel config set-key            # 粘贴 API Key（不回显）
.venv/bin/report2excel config test               # 测试连通性

# 转换单张图片 / 多页 PDF / 整个文件夹
.venv/bin/report2excel convert daily_report.pdf --pages 1-3 -o out.xlsx --save-history
.venv/bin/report2excel history list              # 查看 SQLite 历史品项均价
```

## 运行测试

```bash
.venv/bin/pytest -v
```
