"""Configuration constants and environment variable reads."""

import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Boolean helpers (used internally and exported for other modules)
# ---------------------------------------------------------------------------
_BOOL_TRUE = {"1", "true", "yes", "y", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def _env_flag(name: str, default: Optional[bool] = None) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in _BOOL_TRUE:
        return True
    if val in _BOOL_FALSE:
        return False
    return default


# ---------------------------------------------------------------------------
# Logging directories
# ---------------------------------------------------------------------------
VRBO_LOG_DIR = Path(os.getenv("VRBO_LOG_DIR", str(PROJECT_ROOT / "logs"))).expanduser()

# ---------------------------------------------------------------------------
# Core settings
# ---------------------------------------------------------------------------
VRBO_BASE = "https://www.vrbo.com"
VRBO_USER_AGENT = os.getenv(
    "VRBO_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
VRBO_PROFILE_DIR = Path(os.getenv("VRBO_PROFILE_DIR", str(Path.home() / ".vrbo_uc_profile"))).expanduser()
VRBO_FRESH_PROFILE = os.getenv("VRBO_FRESH_PROFILE", "0").strip().lower() in ("1", "true", "yes")
VRBO_EXTRA_CHROME_ARGS = os.getenv("VRBO_EXTRA_CHROME_ARGS", "").strip()
VRBO_COOKIE_STRING = os.getenv("VRBO_COOKIE_STRING", "").strip()
VRBO_COOKIES_JSON = os.getenv("VRBO_COOKIES_JSON", "").strip()
VRBO_SCROLL_PAUSE = float(os.getenv("VRBO_SCROLL_PAUSE", "0.4"))
VRBO_MAX_PAGES = int(os.getenv("VRBO_MAX_PAGES", "1"))
VRBO_NAVIGATION_DELAY = float(os.getenv("VRBO_NAVIGATION_DELAY", "2.5"))
VRBO_FORCE_TOMORROW = os.getenv("VRBO_FORCE_TOMORROW", "1").strip().lower() in ("1", "true", "yes")
VRBO_DATA_DIR = Path(os.getenv("VRBO_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser()
VRBO_TARGET_TYPE = "vrbo_detail"
VRBO_MAX_DETAIL_TARGETS = int(os.getenv("VRBO_MAX_DETAIL_TARGETS", "0"))
VRBO_SAVE_DETAIL_HTML = os.getenv("VRBO_SAVE_DETAIL_HTML", "0").strip().lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Viewport / display settings
# ---------------------------------------------------------------------------
_GLOBAL_VIEWPORT_W = int(os.getenv("VIEWPORT_W", "1920"))
_GLOBAL_VIEWPORT_H = int(os.getenv("VIEWPORT_H", "1080"))
_GLOBAL_DEVICE_SCALE = float(os.getenv("DEVICE_SCALE", "1"))
VRBO_VIEWPORT_W = int(os.getenv("VRBO_VIEWPORT_W", str(_GLOBAL_VIEWPORT_W)))
VRBO_VIEWPORT_H = int(os.getenv("VRBO_VIEWPORT_H", str(_GLOBAL_VIEWPORT_H)))
VRBO_DEVICE_SCALE = float(os.getenv("VRBO_DEVICE_SCALE", str(_GLOBAL_DEVICE_SCALE)))
VRBO_CHROME_LANG = os.getenv("VRBO_CHROME_LANG", "es-ES")

# ---------------------------------------------------------------------------
# Headless / GPU / Sandbox flags
# ---------------------------------------------------------------------------
_GLOBAL_HEADLESS = True
VRBO_HEADLESS = _env_flag("VRBO_HEADLESS", _GLOBAL_HEADLESS if _GLOBAL_HEADLESS is not None else False) or False
VRBO_DISABLE_GPU = _env_flag("VRBO_DISABLE_GPU", True)
VRBO_DISABLE_SANDBOX = _env_flag("VRBO_DISABLE_SANDBOX", True)
