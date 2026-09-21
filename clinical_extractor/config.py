from __future__ import annotations
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CLINICAL_EXTRACTOR_DATA", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "clinical_extractor.sqlite3"
SETTINGS_PATH = DATA_DIR / "settings.json"
PROFILE_DIR = Path(os.getenv("CLINICAL_EXTRACTOR_PROFILES", ROOT / "profiles"))

for p in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, PROFILE_DIR):
    p.mkdir(parents=True, exist_ok=True)

@dataclass
class Settings:
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    pp_device: str = "cpu"
    use_doc_orientation_classify: bool = True
    use_doc_unwarping: bool = False
    use_textline_orientation: bool = True
    use_formula_recognition: bool = False
    max_text_chars: int = 12000
    mock_mode: bool = False


def load_settings() -> Settings:
    if SETTINGS_PATH.exists():
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        base = asdict(Settings())
        base.update({k: v for k, v in raw.items() if k in base})
        return Settings(**base)
    settings = Settings()
    save_settings(settings)
    return settings


def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
