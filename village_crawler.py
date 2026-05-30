"""
Village Cinemas Crawler — fetches showtimes and IMDB ratings for movies
currently playing at Village Cinemas (Greece).
"""

import argparse
import datetime
import json
import logging
import os
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from imdbinfo import search_title, get_movie as imdb_get_movie

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

class fg:
    """Foreground ANSI colour codes."""
    blue = "\033[34m"
    cyan_bold = "\033[1;34m"
    red_bold = "\033[1;31m"
    cyan = "\033[96m"
    red = "\033[31m"
    green = "\033[1;32m"
    yellow = "\033[1;33m"
    grey = "\033[1;30m"
    reset = "\033[0m"
    bold = "\033[1m"

    @staticmethod
    def rgb(r: int, g: int, b: int) -> str:
        return f"\u001b[38;2;{r};{g};{b}m"


class bg:
    """Background ANSI colour codes."""
    red = "\033[41m"
    green = "\033[42m"
    yellow = "\033[43m"

    @staticmethod
    def rgb(r: int, g: int, b: int) -> str:
        return f"\u001b[48;2;{r};{g};{b}m"


def strip_ansi(text: str) -> str:
    """Return *text* with all ANSI escape sequences removed."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


def center(text: str, width: int) -> str:
    """Centre *text* that may contain ANSI codes inside *width* columns."""
    visible = len(strip_ansi(text))
    pad = max(0, width - visible) // 2
    return " " * pad + text


def terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

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
    is_limited: bool

# ---------------------------------------------------------------------------
# Cinema catalogue
# ---------------------------------------------------------------------------

CINEMAS: dict[str, str] = {
    "Maroussi - The Mall Athens": "21",
    "Rentis - Village Shopping and more...": "01",
    "Thessaloniki - Mediterranean Cosmos": "22",
    "Agios Dimitrios - Athens Metro Mall": "26",
    "Pagrati - Pagrati Village": "03",
    "Volos - Volos Village": "23",
    "Larissa - Fashion City Outlet": "30",
}

# ---------------------------------------------------------------------------
# Pricing table
# ---------------------------------------------------------------------------

PRICE_TABLE_LINES = [
    "┌──────────────────┬───────────┐",
    "│   normal cost    │ what's up │",
    "│─────────┬────────┼───────────│",
    "│ classic │  9,5 € │   6,65 €  │",
    "│  dolby  │ 10,5 € │   7,35 €  │",
    "│   vmax  │ 12,0 € │   8,40 €  │",
    "│   gold  │ 24,5 € │           │",
    "└─────────┴────────┴───────────┘",
]

# ---------------------------------------------------------------------------
# Village Cinemas scraper
# ---------------------------------------------------------------------------

VILLAGE_URL = "https://www.villagecinemas.gr/en/tickets/film-choice"
IMDB_UA = (
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
            is_limited=bool(screen["isLimited"]),
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
            "movie_id": record["movieId"],
            "title": title,
            "days": days,
            "village_plot": desc,
            "length": record["dur"],
            "village_url": record["url"],
            "trailer_url": trailer,
            "imdb_rating": "?",
            "imdb_url": "",
            "imdb_plot": "",
        })
        print(f"  {fg.green}[✓]{fg.reset} Crawling Village: {title}  ")

    return movies

# ---------------------------------------------------------------------------
# IMDB enrichment
# ---------------------------------------------------------------------------

def _fetch_imdb_for(movie: dict) -> None:
    """Mutate *movie* in-place with IMDB info (rating, URL, plot)."""
    title = movie["title"]
    try:
        results = search_title(title)
        if not results or not results.titles:
            raise ValueError("No IMDB results")

        current_year = datetime.datetime.now().year
        recent = next(
            (t for t in results.titles[:5] if getattr(t, "year", None) in (current_year - 1, current_year)),
            results.titles[0],
        )
        imdb_id = recent.imdb_id
        imdb_movie = imdb_get_movie(imdb_id)

        movie["imdb_rating"] = imdb_movie.rating if imdb_movie.rating is not None else "?"
        movie["imdb_url"] = f"https://www.imdb.com/title/{imdb_id}/"

        plot = getattr(imdb_movie, "plot", None) or getattr(imdb_movie, "plot_outline", None)

        # Fallback: scrape IMDB page for plot
        if not plot:
            resp = requests.get(movie["imdb_url"], headers={"User-Agent": IMDB_UA}, timeout=10)
            imdb_soup = BeautifulSoup(resp.text, "html.parser")
            plot_elem = imdb_soup.find("p", {"data-testid": "plot"})
            if plot_elem:
                span = plot_elem.find("span", recursive=False)
                plot = span.text.strip() if span else ""

        movie["imdb_plot"] = plot or ""
        print(f"  {fg.green}[✓]{fg.reset} Crawled IMDB: {title}")

    except Exception as exc:
        log.debug("IMDB fetch failed for %s: %s", title, exc)
        movie["imdb_rating"] = "?"
        movie["imdb_url"] = ""


def enrich_with_imdb(movies: list[dict], max_workers: int = 8) -> None:
    """Fetch IMDB info for every movie using a thread pool."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_imdb_for, m): m for m in movies}
        for future in as_completed(futures):
            future.result()  # propagate exceptions if any

# ---------------------------------------------------------------------------
# Cache helpers (JSON-based)
# ---------------------------------------------------------------------------

CACHE_DIR = Path(__file__).resolve().parent / ".cache"


def _cache_path(cinema_name: str) -> Path:
    safe = re.sub(r"[^\w]+", "_", cinema_name.lower()).strip("_")
    return CACHE_DIR / f"{safe}.json"


def save_cache(cinema_name: str, movies: list[dict]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    payload = {
        "cached_at": datetime.datetime.now().isoformat(),
        "movies": movies,
    }
    _cache_path(cinema_name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_cache(cinema_name: str, max_age_hours: int = 12) -> Optional[list[dict]]:
    """Return cached movies or *None* if the cache is stale / missing."""
    path = _cache_path(cinema_name)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        path.unlink(missing_ok=True)
        return None

    cached_at = datetime.datetime.fromisoformat(data["cached_at"])
    age = datetime.datetime.now() - cached_at
    if age > datetime.timedelta(hours=max_age_hours):
        log.info("Cache expired (%s old).", age)
        path.unlink(missing_ok=True)
        return None

    movies = data.get("movies", [])
    if not movies:
        path.unlink(missing_ok=True)
        return None

    # Discard cache if every showtime day is in the past
    today = datetime.date.today()
    all_days: list[datetime.date] = []
    for m in movies:
        for day_str in m["days"]:
            d, mo = map(int, day_str.split("/"))
            all_days.append(datetime.date(today.year, mo, d))

    if all_days and all(d < today for d in all_days):
        log.info("All cached dates are in the past — refreshing.")
        path.unlink(missing_ok=True)
        return None

    return movies


def clear_cache(cinema_name: str) -> None:
    path = _cache_path(cinema_name)
    if path.exists():
        path.unlink()
        print(f"  {fg.green}[✓]{fg.reset} Cache cleared for {cinema_name}.")
    else:
        print(f"  {fg.yellow}[~]{fg.reset} No cache to clear.")

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _rating_color(rating) -> str:
    if rating == "?":
        return fg.red
    r = float(rating)
    if r >= 7:
        return fg.green
    if r >= 6:
        return fg.yellow
    return fg.red


def _showtime_badge(st: dict) -> str:
    """Build the coloured tag string for a single showtime."""
    parts: list[str] = []
    if st["is_dolby"]:
        parts.append(f"{fg.grey}(dolby){fg.reset}")
    if st["is_sphera"]:
        parts.append(f"{fg.green}(sphera){fg.reset}")
    if st["is_imax"]:
        parts.append(f"{fg.green}(IMax){fg.reset}")
    if st["is_3d"]:
        parts.append(f"{fg.red}(3D){fg.reset}")
    if st["is_imax_3d"]:
        parts.append(f"{fg.red}(IMax3D){fg.reset}")

    screen = st["screen_name"]
    if "VMax" in screen:
        parts.insert(0, f"{fg.yellow}(VMax){fg.reset}")
    elif "GOLD" in screen:
        parts.insert(0, f"{fg.yellow}(Gold){fg.reset}")

    return " ".join(parts)

def print_movies(
    movies: list[dict],
    search_day: str,
    search_time: Optional[str],
    cinema_name: str,
) -> None:
    cols = terminal_width()
    now = datetime.datetime.now()
    today_str = now.strftime("%d/%m")

    if search_time:
        h, m = map(int, search_time.split(":"))
        ref_time = datetime.time(h, m)
    else:
        ref_time = now.time()

    # Price table
    print(fg.green)
    for line in PRICE_TABLE_LINES:
        print(center(line, cols))
    print(fg.reset)

    # Cinema header
    print(center(f"{fg.red_bold}{cinema_name}{fg.reset}", cols))
    print()

    skipped_past = 0
    total_with_day = 0

    for movie in movies:
        day_showtimes: list[dict] = movie["days"].get(search_day, [])
        if not day_showtimes:
            continue
        total_with_day += 1

        length = movie["length"]
        delta = datetime.timedelta(minutes=int(length)) if length and length != "?" else None

        entries: list[str] = []
        all_past = True

        for st in day_showtimes:
            st_time = datetime.datetime.strptime(st["hour"], "%H:%M").time()

            # Apply time filter whenever -t is supplied
            if search_time and st_time < ref_time:
                continue

            # If no explicit time was supplied and we're viewing today,
            # hide screenings that already started.
            if not search_time and search_day == today_str and st_time < ref_time:
                continue

            all_past = False
            badge = _showtime_badge(st)

            if delta:
                end = (datetime.datetime.combine(datetime.date.today(), st_time) + delta).strftime("%H:%M")
                entry = (
                    f"{fg.cyan_bold}{st['hour']}{fg.reset}-"
                    f"{fg.red_bold}{end}{fg.reset}"
                )
            else:
                entry = (
                    f"{fg.cyan_bold}{st['hour']}{fg.reset}"
                )
            entries.append(entry.strip())

        if not entries:
            if all_past:
                skipped_past += 1
            continue

        # ── Title bar ──
        rating = movie["imdb_rating"]
        color = _rating_color(rating)
        title_str = f" {movie['title']} ({color}{rating}{fg.cyan}) "
        visible_title_len = len(strip_ansi(title_str))
        bar_len = max(0, cols - visible_title_len)
        half = bar_len // 2
        bar_char = "\u2501"
        print(f"{fg.cyan}{bar_char * half}{title_str}{fg.cyan}{bar_char * half}{fg.reset}")

        # Links
        links = fg.grey + urllib.parse.quote(movie["village_url"], safe=":/")
        if movie["trailer_url"]:
            links += "  " + movie["trailer_url"]
        links += fg.reset
        print(center(links, cols))

        # Showtimes
        times_line = "  ".join(entries)
        print(center(times_line, cols))
        print()

        # Plot (word-wrapped)
        plot = movie.get("village_plot", "")
        if plot:
            max_w = min(cols - 4, 100)
            words = plot.split()
            lines: list[str] = []
            cur = ""
            for w in words:
                if cur and len(cur) + 1 + len(w) > max_w:
                    lines.append(cur)
                    cur = w
                else:
                    cur = f"{cur} {w}" if cur else w
            if cur:
                lines.append(cur)
            for ln in lines:
                print(center(ln, cols))
        print()

    if total_with_day > 0 and skipped_past == total_with_day:
        print(center("No more movies playing today.", cols))

# ---------------------------------------------------------------------------
# Interactive cinema picker
# ---------------------------------------------------------------------------

def pick_cinema() -> tuple[str, str]:
    """Prompt the user to choose a cinema; returns (name, id)."""
    names = list(CINEMAS.keys())
    print(f"\n  {fg.bold}Select a cinema:{fg.reset}\n")
    for i, name in enumerate(names, 1):
        print(f"    {fg.cyan}{i}.{fg.reset} {name}")
    print()

    while True:
        try:
            choice = input(f"  {fg.yellow}>{fg.reset} Enter number [1-{len(names)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                name = names[idx]
                return name, CINEMAS[name]
        except (ValueError, EOFError):
            pass
        print(f"  {fg.red}Invalid choice.{fg.reset}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl Village Cinemas showtimes and enrich with IMDB ratings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python village_crawler.py                     # today, interactive cinema picker\n"
            "  python village_crawler.py -c 21               # The Mall Athens, today\n"
            "  python village_crawler.py -d 25/04            # specific date\n"
            "  python village_crawler.py -d 25/04 -t 20:00   # date + start-after time\n"
            "  python village_crawler.py --clear              # clear cache then fetch\n"
            "  python village_crawler.py --list               # list cinema IDs\n"
        ),
    )
    parser.add_argument(
        "-c", "--cinema",
        help="Cinema ID (use --list to see IDs). If omitted, an interactive picker is shown.",
    )
    parser.add_argument(
        "-d", "--date",
        help="Show date in DD/MM format (default: today).",
    )
    parser.add_argument(
        "-t", "--time",
        help="Only show screenings starting after HH:MM.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear cached data for the selected cinema and re-fetch.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_cinemas",
        help="List available cinemas and exit.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached data and always fetch fresh.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # --list
    if args.list_cinemas:
        print(f"\n  {fg.bold}Available cinemas:{fg.reset}\n")
        for name, cid in CINEMAS.items():
            print(f"    {fg.cyan}{cid}{fg.reset}  {name}")
        print()
        return

    # Resolve cinema
    if args.cinema:
        cinema_id = args.cinema
        cinema_name = next((k for k, v in CINEMAS.items() if v == cinema_id), f"Cinema {cinema_id}")
    else:
        cinema_name, cinema_id = pick_cinema()

    # --clear
    if args.clear:
        clear_cache(cinema_name)

    # Resolve date / time (new flags take precedence over legacy positional)
    search_day = args.date or datetime.datetime.now().strftime("%d/%m")
    search_time = args.time

    # Load or fetch data
    movies: Optional[list[dict]] = None
    if not args.no_cache and not args.clear:
        movies = load_cache(cinema_name)
        if movies is not None:
            print(f"\n  {fg.grey}Using cached data. Pass --no-cache or --clear to refresh.{fg.reset}\n")

    if movies is None:
        print()
        movies = crawl_village_titles(cinema_id)
        print()
        enrich_with_imdb(movies)
        print()

        # Sort by rating descending (unknown last)
        movies.sort(
            key=lambda m: float(m["imdb_rating"]) if m["imdb_rating"] != "?" else -1,
            reverse=True,
        )

        save_cache(cinema_name, movies)

    # Filter to requested day
    day_movies = [m for m in movies if search_day in m["days"]]

    print_movies(day_movies, search_day, search_time, cinema_name)


if __name__ == "__main__":
    main()
