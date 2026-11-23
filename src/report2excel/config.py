"""应用配置：读写用户数据目录下的 config.yaml（仿 CardMaker 风格）。

配置文件默认保存在用户数据目录（macOS 为 ~/Library/Application Support/Report2Excel/），
不放在项目目录里，避免 API Key 被提交进 git。
测试或隔离运行时可用环境变量 REPORT2EXCEL_HOME 覆盖。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from platformdirs import user_data_dir
from pydantic import BaseModel, Field

APP_NAME = "Report2Excel"

# 多模态大模型预设：只填 API Key 即可使用
LLM_PRESETS: dict[str, dict] = {
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-plus",
        "models": ["qwen-vl-plus", "qwen-vl-max", "qwen3.8-max"],
        "extra_body": {},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.8-flash",
        "models": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-4-hydrogen"],
        "extra_body": {},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini",
        "models": ["gpt-5-mini", "gpt-4o-mini", "gpt-5.6-luna"],
        "extra_body": {},
    },
    "claude": {
        "base_url": "https://api.anthropic.com/v1/",
        "model": "claude-sonnet-5-5",
        "models": ["claude-sonnet-5-5", "claude-haiku-5-5"],
        "extra_body": {},
        "json_mode": False,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5vl:7b",
        "models": ["qwen2.5vl:7b", "qwen2.5vl:3b"],
        "extra_body": {},
    },
    "local-hydrogen": {
        "base_url": "http://127.0.0.1:8052/v1",
        "model": "gemini-4-hydrogen",
        "models": ["gemini-4-hydrogen", "gemini-3.8-flash"],
        "extra_body": {"reasoning_effort": "low"},
        "json_mode": False,
        "default_key": "dummy",
    },
    "local-flash": {
        "base_url": "http://127.0.0.1:8051/v1",
        "model": "gemini-3.8-flash",
        "models": ["gemini-3.8-flash"],
        "extra_body": {},
        "json_mode": False,
        "default_key": "dummy",
    },
}


class LLMSettings(BaseModel):
    provider: str = "gemini"
    base_url: str = LLM_PRESETS["gemini"]["base_url"]
    model: str = LLM_PRESETS["gemini"]["model"]
    api_key: str = ""
    json_mode: bool = True
    temperature: float = 0.1  # 单据抽取需要稳定准确，低温减少幻觉
    timeout: float = 120.0
    extra_body: dict = Field(default_factory=lambda: dict(LLM_PRESETS["gemini"]["extra_body"]))

    @property
    def ready(self) -> bool:
        return bool(self.api_key) or self.provider in ("ollama", "local-hydrogen", "local-flash")

    def apply_preset(self, name: str) -> None:
        preset = LLM_PRESETS[name]
        self.provider = name
        self.base_url = preset["base_url"]
        self.model = preset["model"]
        self.extra_body = dict(preset["extra_body"])
        self.json_mode = preset.get("json_mode", True)
        if "default_key" in preset:
            self.api_key = preset["default_key"]


class ValidationSettings(BaseModel):
    price_deviation_limit: float = 0.35  # 相对历史均价变动超过 ±35% 标黄警告
    math_tolerance: float = 0.01  # 允许的浮点误差（元/韩元）
    min_history_samples: int = 1  # 历史库至少有几条记录才触发单价偏离警告


class Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    dpi: int = 200
    max_workers: int = 3


def app_home() -> Path:
    override = os.environ.get("REPORT2EXCEL_HOME")
    root = Path(override) if override else Path(user_data_dir(APP_NAME))
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_path() -> Path:
    return app_home() / "config.yaml"


def db_path() -> Path:
    return app_home() / "history.sqlite3"


def load_settings() -> Settings:
    path = config_path()
    if not path.exists():
        return Settings()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(raw)


def save_settings(settings: Settings) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(settings.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def mask_key(key: str) -> str:
    if not key:
        return "(未设置)"
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def clean_pasted_key(raw: str) -> tuple[str, str]:
    """清理粘贴时误带的空格、换行或 Bearer 前缀。"""
    text = raw.strip()
    note = ""
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
        note = "已自动去掉开头的 Bearer 前缀。"
    cleaned = re.sub(r"\s+", "", text)
    if cleaned != text and not note:
        note = "已自动去掉粘贴内容中的空白字符。"
    return cleaned, note
