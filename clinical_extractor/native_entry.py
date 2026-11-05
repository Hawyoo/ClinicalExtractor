from __future__ import annotations

import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _portable_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def _find_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        try:
            stream.bind(("127.0.0.1", 8765))
            return 8765
        except OSError:
            stream.bind(("127.0.0.1", 0))
            return int(stream.getsockname()[1])


def _configure_portable_environment() -> tuple[Path, Path]:
    root = _portable_root()
    data_dir = root / "data"
    logs_dir = root / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CLINICAL_EXTRACTOR_DATA"] = str(data_dir)
    # Keep PaddleX's model cache with the portable application as well.
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(root / "models" / "paddlex-cache"))
    # A Portable package carries a prepared model cache.  Avoid a needless
    # model-source probe at startup; if a model is missing PaddleX still gives
    # a clear local error rather than silently relying on an internet link.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
    return root, logs_dir


def run_app_service(port: int) -> int:
    _, logs_dir = _configure_portable_environment()

    log_path = logs_dir / "launcher.log"
    log_stream = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = log_stream
    sys.stderr = log_stream
    print(f"\n[{datetime.now().isoformat(timespec='seconds')}] ClinicalExtractor app service started")

    # PyInstaller executes this file as the application entry point, where
    # package-relative imports have no parent package. Use the absolute import
    # so source and frozen runs share the same entry path.
    from clinical_extractor.main import app
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--app-service", action="store_true")
    parser.add_argument("--port", type=int, default=None)
    args, _ = parser.parse_known_args()
    requested_port = args.port or int(os.getenv("CLINICAL_EXTRACTOR_PORT", "0"))
    if args.app_service:
        return run_app_service(requested_port or _find_port())

    # Double-clicking ClinicalExtractor.exe is the normal Portable workflow.
    # The companion launcher owns the friendly startup window and starts this
    # same executable again with --app-service, so there is no console window.
    launcher = _portable_root() / "portable-startup.ps1"
    if launcher.exists():
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher)],
            cwd=str(_portable_root()),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return 0
    return run_app_service(requested_port or _find_port())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
