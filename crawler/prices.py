"""Ticket prices fetched from the Village site, matched to each showtime."""

import datetime
import json
import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .cache import CACHE_DIR
from .terminal import fg
from .village import USER_AGENT

log = logging.getLogger(__name__)

PRICES_URL = "https://www.villagecinemas.gr/en/ticket-categories/"
OFFERS_URL = "https://www.villagecinemas.gr/en/offers"
PRICES_MAX_AGE_HOURS = 24

_PRICE_RE = re.compile(r"€\s*(\d{1,3}(?:[.,]\d{1,2})?)|(\d{1,3}(?:[.,]\d{1,2})?)\s*€")


def _prices_in(text: str) -> list[float]:
    return [float((a or b).replace(",", ".")) for a, b in _PRICE_RE.findall(text)]


def _price_label(text: str) -> str:
    label = _PRICE_RE.sub(" ", text)
    label = re.sub(r"\s+", " ", label).strip(" :-–—/|.,")
    return label if len(label) <= 45 else label[:44].rstrip() + "…"


def _parse_price_page(html: str) -> list[tuple[str, list[float]]]:
    """Extract (ticket category, [prices]) rows from the ticket-categories page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    main = soup.find("main") or soup.body or soup
    rows: list[tuple[str, list[float]]] = []

    # 1) Proper tables
    for tr in main.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        prices = [p for c in cells for p in _prices_in(c)]
        label = _price_label(" ".join(c for c in cells if not _PRICE_RE.search(c)))
        if prices and label:
            rows.append((label, prices))

    # 2) Free text: every block that mentions a € price
    if not rows:
        for node in main.find_all(string=_PRICE_RE):
            block = node.find_parent(["li", "p", "td", "h2", "h3", "h4", "h5", "div"])
            text = block.get_text(" ", strip=True) if block else str(node)
            if len(text) > 160:
                text = str(node).strip()
            label = _price_label(text)
            if not re.search(r"\w", label):  # price on its own line: use the nearest heading
                heading = node.find_previous(["h2", "h3", "h4", "h5", "strong", "b"])
                label = _price_label(heading.get_text(" ", strip=True)) if heading else ""
            prices = _prices_in(text)
            if label and prices:
                rows.append((label, prices))

    seen, unique = set(), []
    for label, prices in rows:
        key = (label.lower(), tuple(prices))
        if key not in seen:
            seen.add(key)
            unique.append((label, prices))
    return unique


def _parse_wednesday_offer(html: str) -> tuple[Optional[int], list[str]]:
    """Return (discount %, [excluded categories]) for the Wednesday offer."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = (re.search(r"(\d{1,2})\s*%[^.]{0,80}?wednesday", text, re.I)
         or re.search(r"wednesday[^.]{0,80}?(\d{1,2})\s*%", text, re.I))
    if not m:
        return None, []
    excluded: list[str] = []
    for ex in re.finditer(r"exception of (?:the )?([^.;,]+?)(?:,| upon| provided|\.|$)", text, re.I):
        excluded += [e.strip().lower() for e in re.split(r"&|\band\b|/", ex.group(1)) if e.strip()]
    return int(m.group(1)), excluded


def fetch_prices() -> Optional[dict]:
    """Fetch ticket prices (cached for a day). Returns None if unavailable."""
    path = CACHE_DIR / "prices.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = datetime.datetime.now() - datetime.datetime.fromisoformat(data["fetched_at"])
        if age < datetime.timedelta(hours=PRICES_MAX_AGE_HOURS) and data.get("rows"):
            return data
    except (OSError, ValueError, KeyError):
        pass

    try:
        resp = requests.get(PRICES_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        rows = _parse_price_page(resp.text)
    except Exception as exc:
        print(f"  {fg.grey}Could not fetch ticket prices: {type(exc).__name__}{fg.reset}")
        return None
    if not rows:
        print(f"  {fg.grey}Could not find prices on {PRICES_URL}{fg.reset}")
        return None

    discount, excluded = None, []
    try:
        offers = requests.get(OFFERS_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
        offers.raise_for_status()
        discount, excluded = _parse_wednesday_offer(offers.text)
    except Exception as exc:
        log.debug("Offers page failed: %s", exc)

    data = {
        "fetched_at": datetime.datetime.now().isoformat(),
        "rows": rows,
        "wed_discount": discount,
        "wed_excluded": excluded,
    }
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _euro(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + "€"


_GENERAL_KEYS = ("general", "standard")
_NOT_GENERAL = ("child", "student")
_SPHERA = ("sphera", "shpera")  # the Village price page spells it "Shpera"
# The Wednesday discount never applies to these halls (per Village's offers page);
# merged with whatever exclusions are parsed from the page.
WED_ALWAYS_EXCLUDED = ("gold", "comfort")


def _find_price(rows: list, include, exclude: tuple = ()) -> Optional[tuple[str, float]]:
    """First (label, price) whose label contains all of *include* and none of *exclude*."""
    include = (include,) if isinstance(include, str) else include
    for label, prices in rows:
        low = label.lower()
        if all(k in low for k in include) and not any(x in low for x in exclude):
            return label, prices[0]  # first price only (no Family Pass)
    return None


def showtime_price(st: dict, data: Optional[dict], wednesday: bool) -> str:
    """Ticket price for one showtime, based on its screen / format."""
    if not data or not data.get("rows"):
        return ""
    rows = data["rows"]
    screen = st["screen_name"].upper()

    if "GOLD" in screen:
        found = _find_price(rows, "gold")
    elif st["is_imax"] or st["is_imax_3d"] or "IMAX" in screen:
        found = _find_price(rows, "imax")
    elif "VMAX" in screen:
        found = _find_price(rows, "vmax")
    elif "COMFORT" in screen:
        found = _find_price(rows, "comfort")
    elif st["is_sphera"] or "SPHERA" in screen:
        found = _find_price(rows, "sphera") or _find_price(rows, "shpera")
    elif st["is_3d"] and st["is_dolby"]:
        found = _find_price(rows, ("3d", "dolby"), ("imax", *_SPHERA))
    elif st["is_3d"]:
        found = _find_price(rows, "3d", ("imax", "dolby", *_SPHERA))
    elif st["is_dolby"]:
        found = _find_price(rows, "dolby", ("imax", "3d", *_SPHERA))
    else:
        found = None

    if not found:  # plain screening, or the format has no price of its own
        found = next(
            (f for k in _GENERAL_KEYS if (f := _find_price(rows, k, _NOT_GENERAL))),
            None,
        )
    if not found:
        return ""

    label, price = found
    discount = data.get("wed_discount")
    excluded = [*(data.get("wed_excluded") or []), *WED_ALWAYS_EXCLUDED]
    hall = f"{label} {st['screen_name']}".lower()
    if wednesday and discount and not any(e and e in hall for e in excluded):
        price = round(price * (1 - discount / 100), 2)
    return _euro(price)


def is_wednesday(day_str: str) -> bool:
    """Is DD/MM (this year, or next year if it's long past) a Wednesday?"""
    try:
        today = datetime.date.today()
        d, m = map(int, day_str.split("/"))
        date = datetime.date(today.year, m, d)
        if (today - date).days > 180:
            date = date.replace(year=today.year + 1)
        return date.weekday() == 2
    except ValueError:
        return False
