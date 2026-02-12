"""Search page scrolling, card extraction, pagination, and city runner."""

import random
import time
from typing import Dict, List, Optional

from selenium.webdriver.common.by import By

from .config import (
    VRBO_MAX_PAGES,
    VRBO_NAVIGATION_DELAY,
    VRBO_SCROLL_PAUSE,
    VRBO_TARGET_TYPE,
)
from .logger import log
from .models import CityCfg
from .storage import LocalDB
from .utils import build_entry_url, clean_url, safe_text


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
