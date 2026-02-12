# Vrbo Scraper — Vacation Rental Data Extraction

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-43B02A?style=flat-square&logo=selenium&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

> Full-featured vacation rental scraper for Vrbo: listing discovery, detail page extraction, pricing, amenities, host info, and geolocation. Handles anti-bot detection with undetected-chromedriver.

## Overview

Scrapes vacation rental listings from [Vrbo](https://www.vrbo.com/) with two-phase extraction:

1. **Discovery phase** — Searches by city/region, paginates through results, collects listing URLs
2. **Detail phase** — Visits each listing to extract full property data including pricing, amenities, rooms, host info, policies, images, and coordinates

Built with `undetected-chromedriver` to handle Vrbo's anti-bot protections, including captcha detection with manual resolution prompts.

## Features

- **City-based search** — Configure cities with check-in/check-out dates, guests, currency
- **Auto-pagination** — Scrolls and clicks through all result pages
- **Deep detail extraction** — 30+ data fields per listing
- **Anti-bot handling** — `undetected-chromedriver` with custom Chrome profiles
- **Captcha detection** — Pauses and prompts when blocked
- **Cookie injection** — Manual cookie support for pre-authenticated sessions
- **Geolocation** — Extracts latitude/longitude from property pages
- **JSON output** — Structured results saved per run
- **Configurable** — Environment variables for all settings

## Data Points Extracted

| Category | Fields |
|----------|--------|
| **Property** | ID, name, type, description, status |
| **Pricing** | Amount, currency, text, plan name |
| **Location** | Address, city, country, latitude, longitude |
| **Rooms** | Room details, bed configuration, sleeps count |
| **Amenities** | Popular amenities, full amenity list |
| **Host** | Name, avatar, languages, contact URL |
| **Policies** | Check-in/out rules, cancellation, house rules |
| **Images** | Up to 12 property images |
| **Search context** | Check-in/out dates, adults, children, region |

## Tech Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-43B02A?style=flat-square&logo=selenium&logoColor=white)

- **undetected-chromedriver** — Bypasses Selenium/automation detection
- **Selenium WebDriver** — Browser automation and DOM interaction
- **Python 3.10+** — Dataclasses, type hints, pathlib

## Installation

```bash
git clone https://github.com/Edioff/vrbo-scraper.git
cd vrbo-scraper
pip install -r requirements.txt
```

## Configuration

### Cities file (`cities.vrbo.json`)

```json
{
  "cities": [
    {
      "name": "Bogota",
      "region_name": "Bogota, Colombia",
      "region_id": "-592318",
      "nights": 2,
      "adults": 2
    }
  ]
}
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VRBO_MAX_PAGES` | `1` | Max search result pages to scrape |
| `VRBO_HEADLESS` | `true` | Run Chrome in headless mode |
| `VRBO_NAVIGATION_DELAY` | `2.5` | Delay between page navigations (seconds) |
| `VRBO_SCROLL_PAUSE` | `0.4` | Pause between scroll actions |
| `VRBO_FORCE_TOMORROW` | `true` | Auto-set check-in to tomorrow |
| `VRBO_MAX_DETAIL_TARGETS` | `0` | Limit detail pages (0 = unlimited) |
| `VRBO_COOKIE_STRING` | — | Manual cookie injection |
| `VRBO_FRESH_PROFILE` | `false` | Use fresh Chrome profile each run |

## Usage

```bash
python vrbo_scraper.py
```

Results are saved to `data/vrbo_results_<timestamp>.json`.

## How It Works

```
1. Load city configurations from cities.vrbo.json
2. Launch Chrome with undetected-chromedriver
3. For each city:
   a. Build search URL with dates/guests/region
   b. Load search page, scroll to load all cards
   c. Extract listing URLs from property cards
   d. Paginate (click "Next") up to VRBO_MAX_PAGES
4. For each discovered listing:
   a. Navigate to detail page
   b. Wait for heading to load
   c. Scroll to trigger lazy-loaded content
   d. Extract __PLUGIN_STATE__ JSON (embedded data)
   e. Parse DOM for amenities, rooms, policies, host
   f. Extract coordinates from meta tags
   g. Save structured data
5. Output all results as JSON
```

## Notes

- Designed for educational and research purposes
- Respect Vrbo's Terms of Service and robots.txt
- Use responsible rate limiting and delays
- Captcha may appear; the scraper pauses for manual resolution

## Author

**Johan Cruz** — Data Engineer & Web Scraping Specialist
- GitHub: [@Edioff](https://github.com/Edioff)
- Available for freelance projects

## License

MIT
