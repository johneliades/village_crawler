"""JSON cache of crawled movies, one file per cinema."""

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Optional

from .terminal import fg

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"  # project root


def _cache_path(cinema_name: str) -> Path:
    safe = re.sub(r"[^\w]+", "_", cinema_name.lower()).strip("_")
    return CACHE_DIR / f"{safe}.json"


def save_cache(cinema_name: str, movies: list[dict], keep_timestamp: bool = False) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    cached_at = datetime.datetime.now().isoformat()
    if keep_timestamp:
        # Preserve the original fetch time so showtimes still expire on schedule
        try:
            old = json.loads(_cache_path(cinema_name).read_text(encoding="utf-8"))
            cached_at = old["cached_at"]
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    payload = {
        "cached_at": cached_at,
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
