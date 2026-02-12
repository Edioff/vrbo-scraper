import contextlib
import json
import os
import random
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

import undetected_chromedriver as uc
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PROJECT_ROOT = Path(__file__).resolve().parent

VRBO_LOG_DIR = Path(os.getenv("VRBO_LOG_DIR", str(PROJECT_ROOT / "logs"))).expanduser()
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


_GLOBAL_VIEWPORT_W = int(os.getenv("VIEWPORT_W", "1920"))
_GLOBAL_VIEWPORT_H = int(os.getenv("VIEWPORT_H", "1080"))
_GLOBAL_DEVICE_SCALE = float(os.getenv("DEVICE_SCALE", "1"))
VRBO_VIEWPORT_W = int(os.getenv("VRBO_VIEWPORT_W", str(_GLOBAL_VIEWPORT_W)))
VRBO_VIEWPORT_H = int(os.getenv("VRBO_VIEWPORT_H", str(_GLOBAL_VIEWPORT_H)))
VRBO_DEVICE_SCALE = float(os.getenv("VRBO_DEVICE_SCALE", str(_GLOBAL_DEVICE_SCALE)))
VRBO_CHROME_LANG = os.getenv("VRBO_CHROME_LANG", "es-ES")
_GLOBAL_HEADLESS = True
VRBO_HEADLESS = _env_flag("VRBO_HEADLESS", _GLOBAL_HEADLESS if _GLOBAL_HEADLESS is not None else False) or False
VRBO_DISABLE_GPU = _env_flag("VRBO_DISABLE_GPU", True)
VRBO_DISABLE_SANDBOX = _env_flag("VRBO_DISABLE_SANDBOX", True)


@dataclass
class CityCfg:
    name: str
    region_name: Optional[str] = None
    region_id: Optional[str] = None
    search_url: Optional[str] = None
    checkin: Optional[str] = None
    checkout: Optional[str] = None
    adults: int = 2
    children: int = 0
    rooms: int = 1
    currency: str = "USD"
    locale: str = "es_CO"
    lang: str = "es"
    nights: int = 1
    sort: str = "PRICE_LOW_TO_HIGH"
    flexibility: str = "0_DAY"


def _force_tomorrow_dates(c: CityCfg) -> CityCfg:
    today = datetime.now().date()
    checkin = today + timedelta(days=1)
    checkout = checkin + timedelta(days=max(1, c.nights))
    c.checkin = checkin.isoformat()
    c.checkout = checkout.isoformat()
    return c


def ensure_dates(c: CityCfg) -> CityCfg:
    if VRBO_FORCE_TOMORROW:
        return _force_tomorrow_dates(c)
    if not c.checkin or not c.checkout:
        return _force_tomorrow_dates(c)
    return c


def clean_url(href: str) -> str:
    try:
        u = urlparse(href)
        base = urlparse(VRBO_BASE)
        scheme = u.scheme or base.scheme
        netloc = u.netloc or base.netloc
        return urlunparse((scheme, netloc, u.path, "", "", ""))
    except Exception:
        return href


def slugify_name(name: Optional[str]) -> str:
    if not name:
        return "colombia"
    safe = "".join(ch if ch.isalnum() else "-" for ch in name.lower())
    safe = "-".join(filter(None, safe.split("-")))
    return safe or "colombia"

def build_entry_url(city: CityCfg) -> str:
    if city.search_url:
        parsed = urlparse(city.search_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))

        def set_param(keys: List[str], value: Optional[str]):
            for key in keys:
                if value:
                    query[key] = value
                else:
                    query.pop(key, None)
        set_param(["checkIn", "startDate", "d1"], city.checkin)
        set_param(["checkOut", "endDate", "d2"], city.checkout)

        query["adults"] = str(max(1, city.adults))
        if city.children:
            query["children"] = str(city.children)
        else:
            query.pop("children", None)

        if city.region_id:
            query["regionId"] = str(city.region_id)

        if getattr(city, "sort", None):
            query["sort"] = city.sort

        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    dest = city.region_name or city.name or "Colombia"
    base = f"{VRBO_BASE}/search"

    query: Dict[str, Any] = {}

    query["destination"] = dest
    if city.region_id:
        query["regionId"] = str(city.region_id)

    if getattr(city, "flexibility", None):
        query["flexibility"] = city.flexibility

    if city.checkin:
        query["d1"] = city.checkin
        query["startDate"] = city.checkin
    if city.checkout:
        query["d2"] = city.checkout
        query["endDate"] = city.checkout

    query["adults"] = str(max(1, city.adults))
    if city.children:
        query["children"] = str(city.children)

    if getattr(city, "sort", None):
        query["sort"] = city.sort

    new_query = urlencode(query, doseq=True)
    return base + "?" + new_query


class LocalDB:
    def __init__(self, source: str = "vrbo"):
        self.source = source
        self._targets = []
        self._next_target_id = 1
        self._results = []
        self._data_dir = VRBO_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def run_start(self) -> int:
        run_id = int(time.time())
        log("VRBO run_start", source=self.source, run_id=run_id)
        return run_id

    def run_end(self, run_id: int, success: bool, notes: str = ""):
        # Save all collected results to JSON
        output_file = self._data_dir / f"vrbo_results_{run_id}.json"
        output_file.write_text(
            json.dumps(self._results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log("VRBO run_end", source=self.source, run_id=run_id, success=success,
            results=len(self._results), output=str(output_file), notes=notes)

    def add_target(self, run_id, typ, clean_url, full_url):
        row = {
            "id": self._next_target_id,
            "run_id": run_id,
            "type": typ,
            "value": clean_url,
            "url": full_url or clean_url,
            "status": "queued",
        }
        self._targets.append(row)
        self._next_target_id += 1

    def list_targets(self, run_id, typ, status="queued"):
        return [r for r in self._targets if r["run_id"] == run_id and r["type"] == typ and r["status"] == status]

    def update_target_status(self, target_id, status):
        for row in self._targets:
            if row["id"] == target_id:
                row["status"] = status
                break

    def save_rental(self, run_id, unique_url, data, lat, lon):
        self._results.append({
            "url": unique_url,
            "latitude": lat,
            "longitude": lon,
            **data,
        })


def load_cities(cfg_path: Path) -> List[CityCfg]:
    if not cfg_path.exists():
        sample = {
            "cities": [
                {
                    "name": "Bogota",
                    "region_name": "Bogota, Distrito Capital, Colombia",
                    "region_id": "-592318",
                    "nights": 2,
                    "adults": 2,
                }
            ]
        }
        cfg_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Se creo cities.vrbo_col.json de ejemplo. Editalo y vuelve a ejecutar.")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    cities = []
    for item in raw.get("cities", []):
        filtered = {k: v for k, v in item.items() if k in CityCfg.__dataclass_fields__}
        cities.append(ensure_dates(CityCfg(**filtered)))
    if not cities:
        raise RuntimeError("cities.vrbo.json sin ciudades validas.")
    return cities


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


def scroll_page(driver):
    container = None
    container_selectors = [
        ".scrollable-result-section.uitk-scrollable-vertical",
        "[data-stid='results']",
    ]
    for sel in container_selectors:
        try:
            container = driver.find_element(By.CSS_SELECTOR, sel)
            if container:
                break
        except Exception:
            continue
    if container:
        stable_at_bottom = 0
        last_seen = -1
        while stable_at_bottom < 3:
            try:
                driver.execute_script("arguments[0].scrollBy(0, arguments[1]);", container, 900)
            except Exception:
                break
            time.sleep(VRBO_SCROLL_PAUSE)
            try:
                current = driver.execute_script(
                    "return arguments[0].scrollTop + arguments[0].clientHeight;", container
                )
                total = driver.execute_script("return arguments[0].scrollHeight;", container)
            except Exception:
                break
            if total and current >= total - 5:
                if abs(last_seen - current) < 5:
                    stable_at_bottom += 1
                else:
                    stable_at_bottom = 1
                    last_seen = current
            else:
                stable_at_bottom = 0
                last_seen = current
        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container)
        except Exception:
            pass
        time.sleep(VRBO_SCROLL_PAUSE)
        return
    driver.execute_script("window.scrollTo(0, 0);")
    height = driver.execute_script("return document.body.scrollHeight")
    current = 0
    while current < height:
        current += 800
        driver.execute_script("window.scrollTo(0, arguments[0]);", current)
        time.sleep(VRBO_SCROLL_PAUSE)
        height = driver.execute_script("return document.body.scrollHeight")


def extract_cards(driver) -> List[Dict[str, Optional[str]]]:
    selectors = [
        '[data-stid="lodging-card-responsive"]',
        '[data-stid="lodging-card"]',
        '[data-stid="property-listing"]',
        'article[data-stid]',
        'article[class*="PropertyCard"]',
    ]
    cards = []
    for sel in selectors:
        elems = driver.find_elements(By.CSS_SELECTOR, sel)
        if elems:
            cards = elems
            break
    results = []
    link_selectors = [
        'a[data-stid="open-hotel-information"]',
        'a[href*="/pdp/"]',
        'a[href*="/vacation-rental/"]',
        'a[href*="ha?"]',
    ]
    for card in cards:
        link = None
        for link_selector in link_selectors:
            try:
                link = card.find_element(By.CSS_SELECTOR, link_selector)
                if link:
                    break
            except Exception:
                continue
        if not link:
            continue
        full_href = link.get_attribute("href")
        href = clean_url(full_href)
        if not href:
            continue
        try:
            title = card.find_element(By.CSS_SELECTOR, "[data-stid*='title'], h2, h3").text
        except Exception:
            title = None
        try:
            price = card.find_element(By.CSS_SELECTOR, "[data-stid*='price'], .uitk-type-500").text
        except Exception:
            price = None
        results.append({"url": href, "full_url": full_href, "title": title, "price": price})
    return results


def _is_disabled(elem) -> bool:
    try:
        disabled_attr = elem.get_attribute("disabled")
        if disabled_attr is not None and disabled_attr not in ("", "false", "False"):
            return True
        aria_disabled = elem.get_attribute("aria-disabled")
        if aria_disabled and aria_disabled.lower() == "true":
            return True
        classes = (elem.get_attribute("class") or "").split()
        if any(cls in {"is-disabled", "uitk-button-disabled"} for cls in classes):
            return True
    except Exception:
        return False
    return False


def click_next(driver) -> bool:
    selectors = [
        '[data-stid="pagination-next"]',
        'button[data-stid="next-button"]',
        'button[aria-label*="Siguiente" i]',
        'button[aria-label*="Next page" i]',
        'button[aria-label*="Next" i]',
        'a[aria-label*="Next" i]',
        'a[rel="next"]',
        'div.scrollable-result-section button.uitk-button-only-icon.uitk-button-primary',
    ]
    for sel in selectors:
        elems = driver.find_elements(By.CSS_SELECTOR, sel)
        if not elems:
            continue
        for elem in elems:
            if not elem.is_displayed():
                continue
            if _is_disabled(elem):
                continue
            if not elem.is_enabled():
                continue
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});",
                    elem,
                )
            except Exception:
                pass
            time.sleep(0.5)
            try:
                elem.click()
                return True
            except Exception:
                continue
    return False


def is_blocked(driver) -> bool:
    html = driver.page_source.lower()
    return ("show us your human side" in html) or ("access denied" in html)


def safe_text(element) -> Optional[str]:
    if not element:
        return None
    try:
        text = element.text.strip()
        return text or None
    except Exception:
        return None


def safe_find_text(container, selector: str) -> Optional[str]:
    try:
        elem = container.find_element(By.CSS_SELECTOR, selector)
        return safe_text(elem)
    except Exception:
        return None


def parse_price_amount(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"([0-9][0-9.,]*)", text)
    if not match:
        return None
    raw = match.group(1)
    value = raw.replace(".", "").replace(",", ".")
    with contextlib.suppress(ValueError):
        return float(value)
    return None


def unique_list(items: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def fetch_plugin_state(driver, fallback_html: Optional[str] = None) -> Dict[str, Any]:
    try:
        state = driver.execute_script("return window.__PLUGIN_STATE__ || null;")
        if isinstance(state, dict):
            return state
    except Exception:
        pass
    html = fallback_html or driver.page_source
    marker = 'window.__PLUGIN_STATE__ = JSON.parse("'
    start = html.find(marker)
    if start == -1:
        return {}
    start += len(marker)
    end = html.find('");', start)
    if end == -1:
        return {}
    raw = html[start:end]
    try:
        decoded = raw.encode("utf-8").decode("unicode_escape")
        return json.loads(decoded)
    except Exception:
        return {}


def parse_content_block(elem) -> Optional[Dict[str, Optional[str]]]:
    if not elem:
        return None
    title = None
    for sel in ("h3", "h4", "h5"):
        matches = elem.find_elements(By.CSS_SELECTOR, sel)
        if matches:
            title = safe_text(matches[0])
            break
    body = safe_text(elem)
    if title and body:
        body = body.replace(title, "", 1).strip()
    return {"title": title, "description": body or None}


def open_dialog_by_button(driver, keywords: List[str]) -> Optional[Any]:
    lowered = [k.lower() for k in keywords]
    buttons = driver.find_elements(By.TAG_NAME, "button")
    for btn in buttons:
        txt = safe_text(btn)
        if not txt:
            continue
        txt_lower = txt.lower()
        if all(k in txt_lower for k in lowered):
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});",
                    btn,
                )
            except Exception:
                pass
            try:
                btn.click()
                WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#app-layer-property-content-section-detailed-dialog-spaces, #app-layer-property-content-section-detailed-dialog-amenities-section-0, div[role='dialog']"))
                )
                return True
            except Exception:
                return None
    return None


def close_dialog(driver, dialog_type: str):
    selectors = {
        "amenities": "#app-layer-property-content-section-detailed-dialog-amenities-section-0 button",
        "spaces": "#app-layer-property-content-section-detailed-dialog-spaces button",
    }
    sel = selectors.get(dialog_type, "div[role='dialog'] button")
    try:
        btn = driver.find_element(By.CSS_SELECTOR, sel)
        btn.click()
    except Exception:
        try:
            driver.find_element(By.CSS_SELECTOR, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
    time.sleep(0.5)


def click_dialog_and_collect(
    driver,
    keywords: List[str],
    item_selector: str,
    parser=None,
    dialog_type: str = "generic",
) -> List[Any]:
    if not open_dialog_by_button(driver, keywords):
        return []
    try:
        dialog_root = driver.find_element(
            By.CSS_SELECTOR,
            "#app-layer-property-content-section-detailed-dialog-spaces, "
            "#app-layer-property-content-section-detailed-dialog-amenities-section-0, "
            "div[role='dialog']",
        )
    except Exception:
        return []
    items = []
    elems = dialog_root.find_elements(By.CSS_SELECTOR, item_selector)
    for elem in elems:
        parsed = parser(elem) if parser else safe_text(elem)
        if isinstance(parsed, dict):
            items.append(parsed)
        elif parsed:
            items.append(parsed)
    close_dialog(driver, "amenities" if "amenities" in [k.lower() for k in keywords] else "spaces")
    return items


def run_city(driver, db: LocalDB, run_id: int, city: CityCfg):
    url = build_entry_url(city)
    log("Procesando ciudad", city=city.name, url=url)
    driver.get(url)
    time.sleep(2)
    if is_blocked(driver):
        log("Pagina bloqueada, resuelve el captcha y pulsa Enter...")
        input()
        time.sleep(2)
    seen = set()
    page_num = 1
    while True:
        scroll_page(driver)
        cards = extract_cards(driver)
        if not cards:
            log("Sin tarjetas visibles", page=page_num)
            if is_blocked(driver):
                log("Resuelve el captcha si aparece y presiona Enter para continuar")
                input()
                continue
            break
        new_count = 0
        for card in cards:
            clean = card.get("url")
            if clean and clean not in seen:
                seen.add(clean)
                db.add_target(run_id, VRBO_TARGET_TYPE, clean, card.get("full_url"))
                new_count += 1
        log("Pagina scrapeada", page=page_num, nuevos=new_count, acumulado=len(seen))
        if new_count == 0:
            log("Sin nuevos resultados; deteniendo paginacion", page=page_num)
            break
        if VRBO_MAX_PAGES > 0 and page_num >= VRBO_MAX_PAGES:
            break
        if not click_next(driver):
            log("Boton siguiente no disponible", page=page_num)
            break
        page_num += 1
        time.sleep(VRBO_NAVIGATION_DELAY + random.uniform(0, 0.5))


def process_detail_targets(driver, db: LocalDB, run_id: int):
    targets = db.list_targets(run_id, VRBO_TARGET_TYPE, status="queued")
    if VRBO_MAX_DETAIL_TARGETS > 0:
        targets = targets[:VRBO_MAX_DETAIL_TARGETS]
    if not targets:
        log("Sin detalles pendientes", run_id=run_id)
        return
    log("Procesando detalles", pendientes=len(targets))
    for row in targets:
        clean_url = row["value"]
        full_url = row["url"] or clean_url
        try:
            data, coordinates = scrape_detail_page(driver, clean_url, full_url)
            if data:
                lat = None
                lon = None
                if coordinates:
                    lat = coordinates.get("lat")
                    lon = coordinates.get("lon")
                db.save_rental(run_id, clean_url, data, lat, lon)
                db.update_target_status(row["id"], "done")
                log("Detalle guardado", url=clean_url)
            else:
                db.update_target_status(row["id"], "empty")
                log("Detalle sin datos", url=clean_url)
        except Exception as exc:
            db.update_target_status(row["id"], "error")
            log("Detalle fallo", url=clean_url, error=str(exc))


def scroll_detail_page(driver):
    checkpoints = [0.25, 0.5, 0.75, 1.0]
    height = driver.execute_script("return document.body.scrollHeight") or 2000
    for fraction in checkpoints:
        driver.execute_script("window.scrollTo(0, arguments[0]);", height * fraction)
        time.sleep(0.4)


def extract_amenities(driver):
    popular = []
    try:
        root = driver.find_element(By.CSS_SELECTOR, "#PopularAmenities")
        items = root.find_elements(By.CSS_SELECTOR, 'li[data-stid^="sp-content-item"] .uitk-text')
        for item in items:
            txt = safe_text(item)
            if txt:
                popular.append(txt)
    except Exception:
        pass
    more = click_dialog_and_collect(
        driver,
        ["amenities"],
        'li[data-stid^="sp-content-item"] .uitk-text',
    )
    combined = unique_list(popular + more)
    return popular, combined


def extract_content_items_from_section(
    driver, keywords: Optional[List[str]] = None
) -> List[Dict[str, Optional[str]]]:
    items = []
    try:
        section = driver.find_element(By.ID, "Rooms")
        blocks = section.find_elements(By.CSS_SELECTOR, '[data-stid="content-item"]')
        for block in blocks:
            parsed = parse_content_block(block)
            if parsed:
                items.append(parsed)
    except Exception:
        pass
    modal_items = click_dialog_and_collect(
        driver,
        keywords or ["rooms", "beds"],
        '[data-stid="content-item"]',
        parser=parse_content_block,
        dialog_type="spaces",
    )
    if modal_items:
        items.extend(modal_items)
    cleaned = []
    seen = set()
    for item in items:
        key = (item.get("title"), item.get("description"))
        if key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def extract_host_info(driver) -> Dict[str, Optional[str]]:
    host = {}
    try:
        host_root = driver.find_element(By.CSS_SELECTOR, "#Host")
    except Exception:
        return host
    host["name"] = safe_find_text(host_root, "h3")
    avatar = None
    try:
        img = host_root.find_element(By.CSS_SELECTOR, "img")
        avatar = img.get_attribute("src")
    except Exception:
        avatar = None
    host["avatar"] = avatar
    languages = []
    try:
        lang_heading = host_root.find_elements(
            By.XPATH,
            ".//h5[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'language')]",
        )
        if lang_heading:
            sibling = lang_heading[0].find_elements(By.XPATH, "./following::div[1]")
            if sibling:
                txt = sibling[0].text.strip()
                if txt:
                    languages = [t.strip() for t in re.split(r",|/", txt) if t.strip()]
    except Exception:
        pass
    host["languages"] = languages
    contact = host_root.find_elements(By.CSS_SELECTOR, 'a[data-stid*="contact-host"]')
    if contact:
        host["contact_url"] = contact[0].get_attribute("href")
    return host


def extract_policies(driver) -> List[Dict[str, Optional[str]]]:
    policies = []
    try:
        root = driver.find_element(By.CSS_SELECTOR, "#Policies")
    except Exception:
        return policies
    grid_items = root.find_elements(By.CSS_SELECTOR, ".uitk-layout-grid-item")
    for item in grid_items:
        parsed = parse_content_block(item)
        if parsed and (parsed.get("title") or parsed.get("description")):
            policies.append(parsed)
    details = root.find_elements(By.CSS_SELECTOR, "details")
    for detail in details:
        summary_text = safe_text(detail.find_element(By.TAG_NAME, "summary")) if detail.find_elements(By.TAG_NAME, "summary") else None
        body_text = safe_text(detail)
        if summary_text or body_text:
            policies.append({"title": summary_text, "description": body_text})
    cleaned = []
    seen = set()
    for item in policies:
        key = (item.get("title"), item.get("description"))
        if key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def extract_images(driver, limit: int = 12) -> List[str]:
    images = []
    elements = driver.find_elements(By.CSS_SELECTOR, "#Overview img")
    for elem in elements:
        src = elem.get_attribute("src")
        if src and src not in images:
            images.append(src)
        if len(images) >= limit:
            break
    return images


def extract_unit_size(page_html: str) -> Optional[str]:
    match = re.search(r"Unit size:\s*([\d.,]+ [^\"<]+)", page_html, re.IGNORECASE)
    if not match:
        return None
    return match.group(0)


def scrape_detail_page(driver, clean_url: str, full_url: str):
    log("Visitando detalle", url=clean_url)
    driver.get(full_url)
    heading_selectors = [
        "#product-headline",
        '[data-stid="summary-headline"] h1',
        '[data-stid="content-hotel-title"] h1',
        'h1[data-stid="content-hotel-title"]',
        'h1.uitk-heading',
    ]
    selector_expr = ", ".join(heading_selectors)
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector_expr))
        )
    except Exception as exc:
        log(
            "Detalle sin encabezado",
            url=clean_url,
            current=driver.current_url,
            title=driver.title,
            error=str(exc),
        )
        if is_blocked(driver):
            log("Detalle bloqueado, resuelve captcha y presiona Enter")
            input()
        return None, None
    if is_blocked(driver):
        log("Detalle bloqueado, resuelve captcha y presiona Enter")
        input()
    time.sleep(0.8)
    scroll_detail_page(driver)
    page_html = driver.page_source
    if VRBO_SAVE_DETAIL_HTML:
        slug = clean_url.rstrip("/").split("/")[-1] or "detail"
        debug_path = LOG_FILE.parent / f"detail_dump_{slug}.html"
        with contextlib.suppress(Exception):
            debug_path.write_text(page_html, encoding="utf-8")
    state = fetch_plugin_state(driver, page_html)
    current_state = state.get("controllers", {}).get("stores", {}).get("currentHotel", {})
    details_payload = current_state.get("detailsPayload", {})
    tealium = details_payload.get("tealiumUtagData", {})
    offer_data = current_state.get("offerSearchData", {})
    search_criteria = current_state.get("searchCriteria", {})
    dest_info = search_criteria.get("destination", {}) if isinstance(search_criteria, dict) else {}
    property_id = current_state.get("hotelId") or tealium.get("hotelId") or clean_url

    title_block = None
    for sel in (
        '[data-stid="summary-headline"]',
        '[data-stid="content-hotel-title"]',
        "#product-headline",
        "header h1",
    ):
        try:
            title_block = driver.find_element(By.CSS_SELECTOR, sel)
            if title_block:
                break
        except Exception:
            continue
    if not title_block:
        debug_name = clean_url.rstrip("/").split("/")[-1] or "detail"
        debug_path = LOG_FILE.parent / f"{debug_name}.html"
        try:
            debug_path.write_text(driver.page_source, encoding="utf-8")
        except Exception:
            pass
        try:
            h1_count = driver.execute_script("return document.querySelectorAll('h1').length;")
            stid_count = driver.execute_script("return document.querySelectorAll('[data-stid]').length;")
        except Exception:
            h1_count = None
            stid_count = None
        log(
            "Detalle sin bloque de titulo",
            url=clean_url,
            saved=str(debug_path),
            current=driver.current_url,
            h1=h1_count,
            stid=stid_count,
        )
        return None, None
    headline = safe_find_text(title_block, "h1")
    property_tag = None
    property_type = None
    tag_spans = title_block.find_elements(By.CSS_SELECTOR, ".uitk-text")
    if tag_spans:
        property_tag = safe_text(tag_spans[0])
        if len(tag_spans) > 1:
            property_type = safe_text(tag_spans[1])
    subtitle = None
    subtitle_divs = title_block.find_elements(By.CSS_SELECTOR, "div.uitk-text")
    if subtitle_divs:
        subtitle = safe_text(subtitle_divs[0])
    address = safe_find_text(title_block, '[data-stid="content-hotel-address"]') or safe_find_text(driver, '[data-stid="content-hotel-address"]')
    if not address:
        address = safe_find_text(driver, '[data-stid="summary-location"] .uitk-text')
        if not address:
            try:
                map_button = driver.find_element(By.CSS_SELECTOR, 'button[aria-label*="View in a map"]')
                address = safe_text(map_button.find_element(By.XPATH, "./preceding-sibling::span[1]"))
            except Exception:
                address = None
    lat = driver.execute_script("var el=document.querySelector('meta[itemprop=\"latitude\"]'); return el ? el.content : null;")
    lon = driver.execute_script("var el=document.querySelector('meta[itemprop=\"longitude\"]'); return el ? el.content : null;")
    lat = float(lat) if lat else None
    lon = float(lon) if lon else None

    description_blocks = driver.find_elements(By.CSS_SELECTOR, '[data-stid="content-markup"]')
    description_long = " ".join([safe_text(block) or "" for block in description_blocks]).strip() or None

    price_block = driver.find_elements(By.CSS_SELECTOR, '[data-stid="property-offer-price-summary"]')
    price_text = safe_text(price_block[0]) if price_block else None
    price_amount = parse_price_amount(price_text)
    price_currency = tealium.get("currencyCode") or offer_data.get("currency") or "USD"

    rooms_summary = None
    try:
        rooms_summary = driver.find_element(
            By.XPATH,
            "//h2[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'rooms')]/following::h3[1]",
        ).text.strip()
    except Exception:
        rooms_summary = None

    rooms = extract_content_items_from_section(driver, ["rooms", "beds"])
    popular_amenities, all_amenities = extract_amenities(driver)
    host_info = extract_host_info(driver)
    policies = extract_policies(driver)
    images = extract_images(driver)
    size_info = extract_unit_size(page_html)

    sleeps = None
    if rooms_summary:
        match = re.search(r"sleeps\s*(\d+)", rooms_summary, re.IGNORECASE)
        if match:
            sleeps = match.group(1)

    sections = {
        "rooms": rooms,
        "amenities": {"popular": popular_amenities, "all": all_amenities},
        "policies": policies,
        "host": host_info,
        "location": {
            "address": address,
            "coordinates": {"lat": lat, "lon": lon},
        },
    }

    size_m2 = None
    if size_info:
        match = re.search(r"([\d.,]+)", size_info)
        if match:
            raw_size = match.group(1).replace(".", "").replace(",", ".")
            with contextlib.suppress(ValueError):
                size_m2 = float(raw_size)

    header_chips = []
    for chip in (property_tag, property_type, subtitle):
        chip = (chip or "").strip()
        if chip and chip not in header_chips:
            header_chips.append(chip)

    search_info = {
        "check_in": offer_data.get("startDate"),
        "check_out": offer_data.get("endDate"),
        "adults": offer_data.get("adults"),
        "children": offer_data.get("children"),
        "destination": dest_info.get("regionName"),
        "region_id": dest_info.get("regionId"),
        "lat_long": dest_info.get("coordinates"),
    }
    country_name = (
        dest_info.get("countryName")
        or dest_info.get("country")
        or tealium.get("propertyCountry")
        or None
    )
    listing_status = tealium.get("listing_status", "active")

    result = {
        "unit_id": str(property_id),
        "unit_name": headline,
        "price_amount": price_amount,
        "price_currency": price_currency,
        "price_text": price_text,
        "price_row_text": price_text,
        "plan_name": property_tag or property_type,
        "cancellation": None,
        "beds_text": rooms_summary,
        "size_m2": size_m2,
        "amenities_parent": popular_amenities,
        "amenities_unit": all_amenities,
        "header_chips": header_chips,
        "sections": sections,
        "long_desc": description_long,
        "comfort_score": None,
        "images": images,
        "listing_status": listing_status,
        "property_type": property_type or subtitle,
        "address": address,
        "city": dest_info.get("regionName") or address,
        "country": country_name,
        "latitude": lat,
        "longitude": lon,
        "_source": {
            "url": full_url,
            "collected_at": datetime.utcnow().isoformat() + "Z",
            "search": search_info,
        },
    }
    return result, {"lat": lat, "lon": lon}


def main():
    data_dir = VRBO_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    db = LocalDB()
    cities = load_cities(PROJECT_ROOT / "cities.vrbo_col.json")
    driver = start_driver()
    try:
        if VRBO_COOKIE_STRING or VRBO_COOKIES_JSON:
            inject_cookies(driver, VRBO_COOKIE_STRING, VRBO_COOKIES_JSON)
        run_id = db.run_start()
        try:
            for city in cities:
                run_city(driver, db, run_id, city)
            process_detail_targets(driver, db, run_id)
            db.run_end(run_id, True, "ok")
            log("Crawler finalizado", run_id=run_id)
        except Exception as exc:
            db.run_end(run_id, False, str(exc))
            log("Crawler fallo", error=str(exc))
            raise
    finally:
        driver.quit()


if __name__ == "__main__":
    print("VRBO Scraper - Standalone Edition")
    print("=" * 40)
    print()
    print("Usage:")
    print("  1. Create a cities.vrbo_col.json file in the same directory as this script.")
    print("     On first run, a sample file will be generated automatically.")
    print()
    print("  2. Run the scraper:")
    print("     python vrbo_scraper.py")
    print()
    print("  3. Results will be saved as JSON files in the data/ directory.")
    print()
    print("Environment variables:")
    print(f"  VRBO_MAX_PAGES        = {VRBO_MAX_PAGES}")
    print(f"  VRBO_MAX_DETAIL_TARGETS = {VRBO_MAX_DETAIL_TARGETS}")
    print(f"  VRBO_HEADLESS         = {VRBO_HEADLESS}")
    print(f"  VRBO_FORCE_TOMORROW   = {VRBO_FORCE_TOMORROW}")
    print(f"  VRBO_DATA_DIR         = {VRBO_DATA_DIR}")
    print(f"  VRBO_LOG_DIR          = {VRBO_LOG_DIR}")
    print(f"  VRBO_SAVE_DETAIL_HTML = {VRBO_SAVE_DETAIL_HTML}")
    print()
    print("Starting scraper...")
    print()
    main()
