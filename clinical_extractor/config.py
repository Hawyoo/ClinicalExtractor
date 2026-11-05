from __future__ import annotations
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# PaddlePaddle 3.3's oneDNN CPU execution path can fail on PP-StructureV3
# model attributes on some Windows hosts.  The standard CPU kernels remain
# fully functional and are materially more reliable for a local desktop app.
# This must be set before PaddlePaddle is imported anywhere in the process.
os.environ.setdefault("FLAGS_use_mkldnn", "0")

FROZEN = bool(getattr(sys, "frozen", False))
# In a PyInstaller package, bundled templates/profiles live in _MEIPASS, while
# mutable records must live next to the executable instead of its temporary
# extraction directory.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) if FROZEN else Path(__file__).resolve().parent.parent
PORTABLE_ROOT = Path(sys.executable).resolve().parent if FROZEN else ROOT
DATA_DIR = Path(os.getenv("CLINICAL_EXTRACTOR_DATA", PORTABLE_ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "clinical_extractor.sqlite3"
SETTINGS_PATH = DATA_DIR / "settings.json"
AUTO_OCR_THREADS = 6  # 7500F: 6 and 11 threads tied on the local two-report benchmark.


def ocr_thread_count(requested: int = 0) -> int:
    logical = max(1, os.cpu_count() or 1)
    return max(1,min(logical, int(requested))) if requested else min(AUTO_OCR_THREADS,max(1,logical-1))
PROFILE_DIR = Path(os.getenv("CLINICAL_EXTRACTOR_PROFILES", ROOT / "profiles"))

for p in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, PROFILE_DIR):
    p.mkdir(parents=True, exist_ok=True)

@dataclass
class Settings:
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    pp_device: str = "cpu"
    ocr_cpu_threads: int = 0
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
