"""Data models used across the scraper."""

from dataclasses import dataclass
from typing import Optional


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
