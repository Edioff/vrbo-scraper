"""Main orchestration: the main() function that runs the full scraper."""

from .config import (
    VRBO_COOKIE_STRING,
    VRBO_COOKIES_JSON,
    VRBO_DATA_DIR,
    PROJECT_ROOT,
)
from .browser import inject_cookies, start_driver
from .detail import process_detail_targets
from .logger import log
from .search import run_city
from .storage import LocalDB
from .utils import load_cities


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
