"""
Village Cinemas Crawler — fetches showtimes and IMDB ratings for movies
currently playing at Village Cinemas (Greece).
"""

import argparse
import datetime
import logging
import sys
from typing import Optional

from crawler.cache import clear_cache, load_cache, save_cache
from crawler.display import print_movies
from crawler.imdb_lookup import enrich_with_imdb, sort_by_rating
from crawler.terminal import fg
from crawler.village import CINEMAS, crawl_village_titles

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)


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


def resolve_cinema(choice: str) -> tuple[str, str]:
    """Resolve -c: menu number (1, 2, …) or part of the cinema name ("mall")."""
    names = list(CINEMAS.keys())
    choice = choice.strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            return names[idx], CINEMAS[names[idx]]
    else:
        matches = [n for n in names if choice.lower() in n.lower()]
        if len(matches) == 1:
            return matches[0], CINEMAS[matches[0]]
        if len(matches) > 1:
            sys.exit(f"'{choice}' matches several cinemas: {', '.join(matches)}")
    sys.exit(f"Unknown cinema '{choice}'. Use --list to see the menu numbers.")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl Village Cinemas showtimes and enrich with IMDB ratings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python village_crawler.py                     # today, interactive cinema picker\n"
            "  python village_crawler.py -c 1                # The Mall Athens (menu #1), today\n"
            "  python village_crawler.py -c maroussi         # same, by name\n"
            "  python village_crawler.py -d 25/04            # specific date\n"
            "  python village_crawler.py -d 25/04 -t 20:00   # date + start-after time\n"
            "  python village_crawler.py --clear              # clear cache then fetch\n"
            "  python village_crawler.py --list               # list cinemas with menu numbers\n"
        ),
    )
    parser.add_argument(
        "-c", "--cinema",
        help="Cinema menu number (1-7) or part of its name, e.g. 'maroussi'. "
             "If omitted, an interactive picker is shown.",
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
        for i, name in enumerate(CINEMAS, 1):
            print(f"    {fg.cyan}{i}.{fg.reset} {name}")
        print()
        return

    # Resolve cinema
    if args.cinema:
        cinema_name, cinema_id = resolve_cinema(args.cinema)
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
            # Retry movies whose IMDB rating is missing (failed or not yet rated)
            failed = [m for m in movies if m.get("imdb_rating") == "?"]
            if failed:
                print(f"  {fg.yellow}[~]{fg.reset} Retrying IMDB for {len(failed)} movie(s) without a rating\n")
                enrich_with_imdb(failed)
                print()
                sort_by_rating(movies)
                save_cache(cinema_name, movies, keep_timestamp=True)

    if movies is None:
        print()
        movies = crawl_village_titles(cinema_id)
        print()
        enrich_with_imdb(movies)
        print()
        sort_by_rating(movies)
        save_cache(cinema_name, movies)

    # Filter to requested day
    day_movies = [m for m in movies if search_day in m["days"]]

    print_movies(day_movies, search_day, search_time, cinema_name)


if __name__ == "__main__":
    main()
