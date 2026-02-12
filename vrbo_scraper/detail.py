"""Detail page extraction: scraping individual property pages."""

import contextlib
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import (
    VRBO_MAX_DETAIL_TARGETS,
    VRBO_SAVE_DETAIL_HTML,
    VRBO_TARGET_TYPE,
)
from .logger import LOG_FILE, log
from .storage import LocalDB
from .utils import parse_price_amount, safe_find_text, safe_text, unique_list


def scroll_detail_page(driver):
    checkpoints = [0.25, 0.5, 0.75, 1.0]
    height = driver.execute_script("return document.body.scrollHeight") or 2000
    for fraction in checkpoints:
        driver.execute_script("window.scrollTo(0, arguments[0]);", height * fraction)
        time.sleep(0.4)


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
    from .search import is_blocked

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
