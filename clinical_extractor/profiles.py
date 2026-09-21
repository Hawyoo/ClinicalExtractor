from __future__ import annotations
from pathlib import Path
import yaml
from .config import PROFILE_DIR


def list_profiles():
    out = []
    for path in sorted(PROFILE_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            out.append({"id": path.stem, "name": data.get("name", path.stem)})
        except Exception:
            out.append({"id": path.stem, "name": path.stem})
    return out


def load_profile(profile_id: str):
    path = PROFILE_DIR / f"{profile_id}.yaml"
    if not path.exists():
        path = PROFILE_DIR / "generic.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
