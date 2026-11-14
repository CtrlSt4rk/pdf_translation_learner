"""Configuration and book progress persistence."""

import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".translation_trainer_config.json"

OLLAMA_DEFAULT_MODELS = ["gemma3:4b", "qwen2.5:3b", "qwen2.5:7b"]
LMSTUDIO_DEFAULT_MODELS = ["google/gemma-3-4b", "qwen2.5-3b-instruct", "qwen2.5-7b-instruct"]

DEFAULT_CONFIG = {
    "provider": "Ollama",
    "model": "gemma3:4b",
    "ollama_host": "http://localhost:11434",
    "lmstudio_host": "http://localhost:1234",
    "src": "English",
    "tgt": "Portuguese",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **saved}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_progress(progress_path: Path) -> dict | None:
    if progress_path.exists():
        return json.loads(progress_path.read_text(encoding="utf-8"))
    return None


def save_progress(progress_path: Path, state: dict) -> None:
    progress_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
