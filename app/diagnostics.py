"""Small file logger for packaged-app diagnostics."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import traceback

from .version import APP_NAME


def diagnostics_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base) / APP_NAME
    else:
        root = Path(tempfile.gettempdir()) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root / "diagnostics.log"


def write_diagnostic(message: str) -> None:
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        diagnostics_log_path().open("a", encoding="utf-8").write(
            f"[{timestamp}] {message}\n"
        )
    except Exception:
        pass


def write_exception(context: str, exc: BaseException) -> None:
    write_diagnostic(
        f"{context}: {exc!r}\n"
        f"frozen={getattr(sys, 'frozen', False)} executable={sys.executable}\n"
        f"{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}"
    )
