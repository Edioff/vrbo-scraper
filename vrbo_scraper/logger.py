"""Logging utilities."""

import json
import time

from .config import VRBO_LOG_DIR

LOG_FILE = VRBO_LOG_DIR / "vrbo_uc.log"


def log(msg: str, **kv):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    if kv:
        try:
            line += " " + json.dumps(kv, ensure_ascii=False, default=str)
        except Exception:
            line += f" {kv}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
