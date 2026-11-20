"""Printing the movie list: title bars, showtimes with tags and prices, plots."""

import datetime
import urllib.parse
from typing import Optional

from .prices import fetch_prices, is_wednesday, showtime_price
from .terminal import fg, center, strip_ansi, terminal_width


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
        parts.append(f"{fg.grey}(Dolby){fg.reset}")
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

    if st.get("soldout"):
        parts.append(f"{fg.red_bold}(sold out){fg.reset}")

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

    # Ticket prices (fetched from the Village site), shown next to each showtime
    prices = fetch_prices()
    wednesday = is_wednesday(search_day)

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
            if badge:
                entry += f" {badge}"
            price = showtime_price(st, prices, wednesday)
            if price:
                entry += f" {fg.green}{price}{fg.reset}"
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

        print(center(fg.grey + urllib.parse.quote(movie["village_url"], safe=":/"), cols))
        if movie["trailer_url"]:
            print(center(fg.grey + urllib.parse.quote(movie["trailer_url"], safe=":/"), cols))
        
        print(fg.reset)

        # Showtimes (wrapped so tags never overflow the terminal)
        rows: list[list[str]] = [[]]
        for e in entries:
            row_len = len(strip_ansi("   ".join(rows[-1] + [e])))
            if rows[-1] and row_len > cols - 4:
                rows.append([])
            rows[-1].append(e)
        for row in rows:
            print(center("   ".join(row), cols))
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
