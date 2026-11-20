"""IMDB ratings: title search (incl. Greek transliteration) and rating fetch."""

import datetime
import json
import logging
import re
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Optional

import requests
from bs4 import BeautifulSoup
from imdbinfo import get_movie as imdb_get_movie

from .terminal import fg
from .village import USER_AGENT

log = logging.getLogger(__name__)

IMDB_SUGGEST_URL = "https://v3.sg.media-imdb.com/suggestion/{first}/{query}.json"
IMDB_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.imdb.com/",
}
_FILM_KINDS = {"movie", "tvMovie", "tvSpecial", "video", "short"}


# --- Title normalisation / Greek transliteration ---------------------------

_GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")

# Screening-format tags Village appends to titles (matched on accent-free uppercase)
_FORMAT_TAG_RE = re.compile(
    r"[\s\-–(]+(IMAX(\s*3D)?|4DX|3D|VMAX|DOLBY(\s*ATMOS)?|ATMOS|SPHERA|"
    r"ΕΛΛΗΝΙΚΗ\s+ΜΕΤΑΓΛ\w*|ΜΕΤΑΓΛ\w*|ΜΕΤ|ΥΠΟΤ\w*|ORIGINAL\s+VERSION)[\s.)]*$"
)

_GREEK_DIGRAPHS_STRICT = {
    "ου": "ou", "αι": "ai", "ει": "ei", "οι": "oi", "αυ": "av", "ευ": "ev",
    "μπ": "mp", "ντ": "nt", "γκ": "gk", "γγ": "ng", "τσ": "ts", "τζ": "tz",
}
# How IMDB usually romanises Greek titles (Καραγκιόζης -> Karagiozis,
# Ντίκενς -> Dikens, Δέντρο -> Dendro): b/d/g at word start, mb/nd/g inside
_GREEK_DIGRAPHS_PHONETIC = {**_GREEK_DIGRAPHS_STRICT, "μπ": "mb", "ντ": "nd", "γκ": "g"}
_GREEK_INITIAL_PHONETIC = {"μπ": "b", "ντ": "d", "γκ": "g"}
_GREEK_LETTERS = dict(zip(
    "αβγδεζηθικλμνξοπρστυφχψω",
    ["a", "v", "g", "d", "e", "z", "i", "th", "i", "k", "l", "m", "n", "x", "o",
     "p", "r", "s", "t", "y", "f", "ch", "ps", "o"],
))


# Words that make a shortened query too vague when they end it
_FILLER_WORDS = {
    "the", "a", "an", "of", "and", "to", "in", "on", "at", "for",
    "ο", "η", "το", "οι", "τα", "του", "τησ", "των", "τον", "την", "τη", "τισ", "τουσ",
    "και", "στο", "στη", "στην", "στον", "με", "σε", "για", "απο",
    "o", "i", "to", "oi", "ta", "tou", "tis", "ton", "tin", "ti", "tous",
    "kai", "sto", "sti", "stin", "ston", "me", "se", "gia", "apo",
}


def _plain(text: str) -> str:
    """Lowercase, strip accents, turn punctuation into single spaces."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().replace("ς", "σ")
    return re.sub(r"[^\w]+", " ", text).strip()


def _greeklish(text: str, phonetic: bool) -> str:
    """Transliterate Greek letters in *text* to Latin."""
    text = _plain(text)
    if phonetic:
        for gr, lat in _GREEK_INITIAL_PHONETIC.items():
            text = re.sub(rf"\b{gr}", lat, text)
    digraphs = _GREEK_DIGRAPHS_PHONETIC if phonetic else _GREEK_DIGRAPHS_STRICT
    for gr, lat in digraphs.items():
        text = text.replace(gr, lat)
    return "".join(_GREEK_LETTERS.get(c, c) for c in text)


def _clean_title(title: str) -> str:
    """Remove trailing screening-format tags (IMAX, 3D, ΜΕΤΑΓΛ., …)."""
    while True:
        m = _FORMAT_TAG_RE.search(title.upper())
        if not m or m.start() == 0:
            return title.strip()
        title = title[: m.start()].rstrip(" -–:(")


def _similar(a: str, b: str) -> float:
    """Similarity of two titles after romanisation (0..1)."""
    a1, b1 = _greeklish(a, True), _greeklish(b, True)
    a2, b2 = _greeklish(a, False), _greeklish(b, False)
    return max(SequenceMatcher(None, a1, b1).ratio(), SequenceMatcher(None, a2, b2).ratio())


def _search_queries(movie: dict) -> list[tuple[str, bool]]:
    """Ordered (query, must_verify) pairs to try against IMDB.

    The cleaned title is trusted as-is (IMDB's own ranking); every fallback
    query must produce a candidate whose title closely matches the query.
    """
    title = _clean_title(movie["title"])
    queries: list[tuple[str, bool]] = [(title, bool(_GREEK_RE.search(title)))]

    if _GREEK_RE.search(title):
        queries.append((_greeklish(title, phonetic=True), True))
        queries.append((_greeklish(title, phonetic=False), True))

    # Drop trailing words (e.g. "ΟΛΙΒΕΡ ΤΟΥΙΣΤ Κάρολος Ντίκενς" -> "ΟΛΙΒΕΡ ΤΟΥΙΣΤ")
    base = [q for q, _ in queries]
    for q in base:
        words = q.split()
        for n in range(len(words) - 1, max(1, len(words) - 3), -1):
            prefix = words[:n]
            content = [w for w in prefix if _plain(w) not in _FILLER_WORDS and _plain(w)]
            last = _plain(prefix[-1])
            if len(content) >= 2 and last and last not in _FILLER_WORDS:
                queries.append((" ".join(prefix), True))

    seen, unique = set(), []
    for q, verify in queries:
        key = _plain(q)
        if key and key not in seen:
            seen.add(key)
            unique.append((q, verify))
    return unique


# --- IMDB search -------------------------------------------------------------

Candidate = tuple[str, Optional[int], str]  # (tt-id, year, IMDB title)


def _imdb_suggest(query: str) -> list[Candidate]:
    """Query IMDB's public search-box suggestion endpoint."""
    q = _plain(query)
    first = q[0] if q[:1].isascii() and q[:1].isalnum() else "x"
    resp = requests.get(
        IMDB_SUGGEST_URL.format(first=first, query=urllib.parse.quote(q)),
        headers=IMDB_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return [
        (d["id"], d.get("y"), d.get("l", ""))
        for d in resp.json().get("d", [])
        if d.get("id", "").startswith("tt") and d.get("qid", "movie") in _FILM_KINDS
    ]


def _imdb_candidates(movie: dict) -> tuple[list[Candidate], str]:
    """Return (candidates, query that matched) for *movie*.

    Tries IMDB's suggestion endpoint with each query in turn; fallback queries
    only count if a candidate's title closely matches. Raises LookupError.
    """
    queries = _search_queries(movie)
    for query, must_verify in queries:
        cands = _imdb_suggest(query)
        if must_verify:
            cands = [c for c in cands if _similar(c[2], query) >= 0.75]
        if cands:
            return cands, query
    raise LookupError("no match — tried " + ", ".join(repr(q) for q, _ in queries))


def _scrape_imdb_rating(url: str) -> Optional[float]:
    """Fallback: read the rating from the IMDB title page's JSON-LD."""
    resp = requests.get(url, headers=IMDB_HEADERS, timeout=10)
    resp.raise_for_status()
    ld = BeautifulSoup(resp.text, "html.parser").find("script", {"type": "application/ld+json"})
    if not (ld and ld.string):
        return None
    rating = (json.loads(ld.string).get("aggregateRating") or {}).get("ratingValue")
    return float(rating) if rating is not None else None


def _fetch_imdb_for(movie: dict) -> None:
    """Mutate *movie* in-place with IMDB info (rating, URL)."""
    title = movie["title"]
    try:
        candidates, matched_query = _imdb_candidates(movie)
        current_year = datetime.datetime.now().year
        imdb_id, _year, imdb_title = next(
            (c for c in candidates[:5] if c[1] in (current_year - 1, current_year)),
            candidates[0],
        )
        movie["imdb_url"] = f"https://www.imdb.com/title/{imdb_id}/"

        rating = None
        try:
            rating = imdb_get_movie(imdb_id).rating
        except Exception as exc:
            log.debug("imdbinfo get_movie failed for %s: %s", title, exc)

        if rating is None:
            try:
                rating = _scrape_imdb_rating(movie["imdb_url"])
            except Exception as exc:
                log.debug("IMDB page scrape failed for %s: %s", title, exc)

        movie["imdb_rating"] = rating if rating is not None else "?"
        shown = movie["imdb_rating"] if rating is not None else "no rating yet"
        via = f", matched “{imdb_title}”" if _plain(matched_query) != _plain(title) else ""
        print(f"  {fg.green}[✓]{fg.reset} Crawled IMDB: {title} {fg.grey}({imdb_id}, {shown}{via}){fg.reset}")

    except Exception as exc:
        reason = str(exc).splitlines()[0][:160] if str(exc) else type(exc).__name__
        print(f"  {fg.red}[✗]{fg.reset} Crawled IMDB: {title} — {type(exc).__name__}: {reason}")
        movie["imdb_rating"] = "?"
        movie["imdb_url"] = ""


def sort_by_rating(movies: list[dict]) -> None:
    """Sort *movies* in-place by IMDB rating, highest first (unknown last)."""
    movies.sort(
        key=lambda m: float(m["imdb_rating"]) if m["imdb_rating"] != "?" else -1,
        reverse=True,
    )


def enrich_with_imdb(movies: list[dict], max_workers: int = 2) -> None:
    """Fetch IMDB info for every movie using a thread pool."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_imdb_for, m): m for m in movies}
        for future in as_completed(futures):
            future.result()  # propagate exceptions if any
