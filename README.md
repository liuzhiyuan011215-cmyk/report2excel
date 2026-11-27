# Report2Excel：图片 / PDF 营业报告 → 带公式与自动校验的 Excel

## 🇰🇷 한국어 요약
- **기능**: 가게 영업 보고서(사진·PDF)에서 품목·수량·단가를 읽고, **Python으로 합계를 다시 계산**해서 틀리면 표시합니다. 단가가 과거 평균과 **±35% 이상** 차이 나면 노란색으로 표시한 Excel(`.xlsx`)을 만듭니다.
- **실행**: 아래 설치 후 `.venv/bin/report2excel demo` (API Key 없이 데모) 또는 `.venv/bin/report2excel-gui`
- **본인 역할**: 개인 프로젝트 — 검증 규칙(재계산·단가 ±35%) 설계와 결과 확인을 직접 했습니다. 구현은 Claude Code를 활용했습니다.

---

把餐厅/门店每日营业报告、进货单（截图、照片、多页 PDF）自动整理为带公式的 Excel：
按页解析（PyMuPDF / Pillow）→ 注入 SQLite 历史品项·单价上下文 → 多模态 LLM 抽取结构化明细 → **Python 独立重算与历史单价 ±35% 校验** → 导出带 Excel 公式、**仅问题行标黄**的 `.xlsx`。

> 架构仿照 `CardMaker`，核心引擎与界面完全解耦（CLI + `PySide6` 桌面端）。

## 快速安装与打开桌面 App

```bash
git clone https://github.com/liuzhiyuan011215-cmyk/report2excel.git
cd report2excel
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/make_mac_launcher.py   # 生成可双击打开的 Report2Excel.app
```

安装好后，macOS 直接双击 **`Report2Excel.app`**，或终端运行 `.venv/bin/report2excel-gui` 即可打开桌面界面（右上角「设置」支持 `local-hydrogen`、`local-flash`、`gemini`、`dashscope`、`openai`、`claude`、`ollama` 一键预设）。

## 1. 一键离线演示（无需 API Key）

内置两个经典测试场景：
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
