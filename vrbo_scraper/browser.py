"""Chrome / undetected-chromedriver setup and cookie injection."""

import contextlib
import json
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List

import undetected_chromedriver as uc
from selenium.common.exceptions import SessionNotCreatedException

from .config import (
    VRBO_BASE,
    VRBO_CHROME_LANG,
    VRBO_DEVICE_SCALE,
    VRBO_DISABLE_GPU,
    VRBO_DISABLE_SANDBOX,
    VRBO_EXTRA_CHROME_ARGS,
    VRBO_FRESH_PROFILE,
    VRBO_HEADLESS,
    VRBO_PROFILE_DIR,
    VRBO_USER_AGENT,
    VRBO_VIEWPORT_H,
    VRBO_VIEWPORT_W,
)
from .logger import log


def resolve_profile_dir(force_fresh: bool = False) -> Path:
    if VRBO_FRESH_PROFILE or force_fresh:
        tmp_dir = Path(tempfile.mkdtemp(prefix="vrbo_uc_profile_"))
        log("Usando perfil temporal para Chrome", path=str(tmp_dir))
        return tmp_dir
    VRBO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return VRBO_PROFILE_DIR


def cleanup_profile_singletons(profile_dir: Path):
    targets = [
        profile_dir / "SingletonLock",
        profile_dir / "SingletonCookie",
        profile_dir / "SingletonSocket",
    ]
    for target in targets:
        try:
            if target.exists():
                target.unlink()
                log("Chrome elimino residual del perfil", file=str(target))
        except Exception as exc:
            log("No se pudo borrar residual del perfil", file=str(target), error=str(exc))


def _build_chrome_options(profile_dir: Path) -> uc.ChromeOptions:
    options = uc.ChromeOptions()
    if VRBO_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument(f"--lang={VRBO_CHROME_LANG}")
    options.add_argument(f"--user-agent={VRBO_USER_AGENT}")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if VRBO_DISABLE_GPU:
        options.add_argument("--disable-gpu")
    if VRBO_DISABLE_SANDBOX:
        options.add_argument("--no-sandbox")
    options.add_argument(f"--window-size={VRBO_VIEWPORT_W},{VRBO_VIEWPORT_H}")
    if abs(VRBO_DEVICE_SCALE - 1.0) > 1e-3:
        options.add_argument(f"--force-device-scale-factor={VRBO_DEVICE_SCALE}")
    if VRBO_EXTRA_CHROME_ARGS:
        extra_args = [arg for arg in shlex.split(VRBO_EXTRA_CHROME_ARGS) if arg]
        if extra_args:
            log("Agregando argumentos extra a Chrome", total=len(extra_args))
            for arg in extra_args:
                options.add_argument(arg)
    return options


def start_driver(force_fresh: bool = False) -> uc.Chrome:
    profile_dir = resolve_profile_dir(force_fresh=force_fresh)
    cleanup_profile_singletons(profile_dir)
    options = _build_chrome_options(profile_dir)
    log(
        "Iniciando Chrome para VRBO",
        headless=VRBO_HEADLESS,
        window=f"{VRBO_VIEWPORT_W}x{VRBO_VIEWPORT_H}",
        lang=VRBO_CHROME_LANG,
        profile=str(profile_dir),
    )
    try:
        driver = uc.Chrome(options=options)
    except SessionNotCreatedException as exc:
        if force_fresh or VRBO_FRESH_PROFILE:
            raise
        log("Chrome no abrio con el perfil guardado, limpiando y reintentando", error=str(exc))
        with contextlib.suppress(Exception):
            shutil.rmtree(profile_dir, ignore_errors=True)
        return start_driver(force_fresh=True)
    if not VRBO_HEADLESS:
        with contextlib.suppress(Exception):
            driver.set_window_size(VRBO_VIEWPORT_W, VRBO_VIEWPORT_H)
    driver.set_page_load_timeout(45)
    return driver


def _parse_cookie_string(cookie: str) -> List[Dict[str, str]]:
    pairs = [c.strip() for c in cookie.split(";") if "=" in c]
    cookies = []
    for pair in pairs:
        name, value = pair.split("=", 1)
        cookies.append({"name": name.strip(), "value": value.strip()})
    return cookies


def inject_cookies(driver, cookies_str: str, cookies_json: str):
    cookies = []
    if cookies_json:
        try:
            data = json.loads(cookies_json)
            if isinstance(data, list):
                cookies.extend(data)
        except Exception as exc:
            log("No se pudo parsear VRBO_COOKIES_JSON", error=str(exc))
    if cookies_str:
        cookies.extend(_parse_cookie_string(cookies_str))
    if not cookies:
        return
    log("Inyectando cookies manuales", total=len(cookies))
    driver.get(VRBO_BASE)
    for cookie in cookies:
        if "domain" not in cookie:
            cookie["domain"] = "www.vrbo.com"
        with_context = {k: v for k, v in cookie.items() if v is not None}
        try:
            driver.add_cookie(with_context)
        except Exception:
            pass
    driver.refresh()
