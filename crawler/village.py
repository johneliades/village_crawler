"""Village Cinemas: cinema list and showtime scraper."""

import datetime
import json
import logging
import re
import sys
from dataclasses import dataclass, asdict

import requests
from bs4 import BeautifulSoup

from .terminal import fg, center, terminal_width

log = logging.getLogger(__name__)

CINEMAS: dict[str, str] = {
    "Maroussi - The Mall Athens": "21",
    "Rentis - Village Shopping and more...": "01",
    "Thessaloniki - Mediterranean Cosmos": "22",
    "Agios Dimitrios - Athens Metro Mall": "26",
    "Pagrati - Pagrati Village": "03",
    "Volos - Volos Village": "23",
    "Larissa - Fashion City Outlet": "30",
}

@dataclass
class Showtime:
    hour: str
    screen_name: str
    soldout: bool
    is_sphera: bool
    is_dolby: bool
    is_3d: bool
    is_imax: bool
    is_imax_3d: bool

VILLAGE_URL = "https://www.villagecinemas.gr/en/tickets/film-choice"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def crawl_village_titles(cinema_id: str) -> list[dict]:
    """Scrape the Village Cinemas website and return movie data for *cinema_id*."""
    response = requests.get(VILLAGE_URL, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    pattern = re.compile(r"var bookingData = (\{.*?)</script>", re.DOTALL)
    match = pattern.search(str(soup))
    if not match:
        log.error("Could not locate bookingData on Village page.")
        sys.exit(1)

    booking_data = json.loads(match.group(1))

    # Resolve cinema name
    cinema_name = next(
        (c["display"] for c in booking_data["filters"]["cinemas"] if c["value"] == cinema_id),
        "Unknown cinema",
    )
    cols = terminal_width()
    print(center(f"{fg.bold}{cinema_name}{fg.reset}", cols))
    print()

    # Build showtime lookup  film_id -> day_str -> [Showtime-dict, …]
    showtimes: dict[str, dict[str, list[dict]]] = {}

    for screen in booking_data["screens"]:
        if screen["cinemaId"] != cinema_id:
            continue

        film_id = screen["scheduledFilmId"]
        dt = datetime.datetime.strptime(screen["showtime"], "%Y-%m-%dT%H:%M:%S")
        day_str = dt.strftime("%d/%m")

        st = Showtime(
            hour=dt.strftime("%H:%M"),
            screen_name=screen["screenName"],
            soldout=bool(screen["soldoutStatus"]),
            is_sphera=bool(screen["isSphera"]),
            is_dolby=bool(screen["isDolby"]),
            is_3d=bool(screen["is3D"]),
            is_imax=bool(screen["isImax"]),
            is_imax_3d=bool(screen["isImax3D"]),
        )

        showtimes.setdefault(film_id, {}).setdefault(day_str, []).append(asdict(st))

    # Sort each day's showtimes by hour
    for film in showtimes.values():
        for day_list in film.values():
            day_list.sort(key=lambda s: s["hour"])

    # Build movie list
    movies: list[dict] = []
    seen_titles: set[str] = set()

    for record in booking_data["records"]:
        if cinema_id not in record["cinemas"]:
            continue
        title = record["title"]
        if title in seen_titles:
            continue
        seen_titles.add(title)

        print(f"  {fg.yellow}[~]{fg.reset} Crawling Village: {title}", end="\r")

        # Map dates to showtimes
        days: dict[str, list[dict]] = {}
        for raw_day in record["dates"]:
            day_str = datetime.datetime.strptime(raw_day, "%Y-%m-%d").strftime("%d/%m")
            film_st = showtimes.get(record["movieId"], {})
            if day_str in film_st:
                days[day_str] = film_st[day_str]

        desc_soup = BeautifulSoup(record["desc"], "html.parser")
        desc = desc_soup.get_text(strip=True)

        trailer = f"https://www.youtube.com/watch?v={record['vid']}" if record.get("vid") else ""

        movies.append({
            "title": title,
            "days": days,
            "village_plot": desc,
            "length": record["dur"],
            "village_url": record["url"],
            "trailer_url": trailer,
            "imdb_rating": "?",
            "imdb_url": "",
        })
        print(f"  {fg.green}[✓]{fg.reset} Crawling Village: {title}  ")

    return movies
