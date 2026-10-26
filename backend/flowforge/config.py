"""Environment loading. Must be imported before anything reads os.environ.

Reads backend/.env if present (simple KEY=VALUE lines; no external dependency). Real environment
variables always win, so `set VAR=...` or a shell export is never overridden by the file.
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = _ENV_PATH) -> int:
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


load_env()
