from __future__ import annotations
from pathlib import Path
import yaml
from .config import PROFILE_DIR




def load_profile():
    path = PROFILE_DIR / 'generic.yaml'
    return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
