"""Pure utility functions."""

import contextlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .config import VRBO_BASE, VRBO_FORCE_TOMORROW
from .models import CityCfg


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


def safe_text(element) -> Optional[str]:
    if not element:
        return None
    try:
        text = element.text.strip()
        return text or None
    except Exception:
        return None


def safe_find_text(container, selector: str) -> Optional[str]:
    from selenium.webdriver.common.by import By
    try:
        elem = container.find_element(By.CSS_SELECTOR, selector)
        return safe_text(elem)
    except Exception:
        return None


def text_or_none(element) -> Optional[str]:
    return safe_text(element)


def _env_flag(name: str, default: Optional[bool] = None) -> Optional[bool]:
    """Re-export from config for convenience."""
    from .config import _env_flag as _config_env_flag
    return _config_env_flag(name, default)
