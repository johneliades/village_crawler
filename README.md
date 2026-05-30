# Village Crawler

Reverse-engineered Village Cinemas (Greece) scraper that retrieves currently
playing movies with showtimes, ticket availability, and IMDB ratings — then
presents everything in a colourful, sorted terminal view.

<p align="center">
  <img src="https://github.com/johneliades/village_crawler/blob/main/preview.jpg" alt="preview" />
</p>

## Features

- Scrapes the Village Cinemas WebTicketing API for live showtimes & availability
- Enriches each movie with its IMDB rating and plot (multi-threaded)
- Sorts movies by IMDB rating (highest first)
- Interactive cinema picker or pass a cinema ID via CLI
- Smart JSON cache (auto-expires after 12 hours or when dates go stale)
- Tags for Dolby, Sphera, VMax, IMAX, 3D, Gold screens

## Installation

Clone the repository:

```bash
git clone https://github.com/johneliades/village_crawler.git
cd village_crawler
```

Create a virtual environment and install dependencies:

**Windows**
```
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```

**Linux / macOS**
```
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

## Usage

Activate the virtual environment first, then:

```bash
# Interactive cinema picker, today's showtimes
python village_crawler.py

# Specify a cinema by ID
python village_crawler.py -c 01

# Specific date (DD/MM)
python village_crawler.py -d 25/06

# Date + only show screenings after a given time
python village_crawler.py -d 25/06 -t 20:00

# Force fresh data (ignore cache)
python village_crawler.py --no-cache

# Clear cache and re-fetch
python village_crawler.py --clear

# List available cinema IDs
python village_crawler.py --list
```

### Cinema IDs

| ID | Cinema                              |
|----|-------------------------------------|
| 21 | Maroussi – The Mall Athens          |
| 01 | Rentis – Village Shopping and more… |
| 22 | Thessaloniki – Mediterranean Cosmos |
| 26 | Agios Dimitrios – Athens Metro Mall |
| 03 | Pagrati – Pagrati Village           |
| 23 | Volos – Volos Village               |
| 30 | Larissa – Fashion City Outlet       |


## Cache

Scraped data is cached as JSON under a `.cache/` directory (auto-created).  
The cache expires automatically after **12 hours** or when all showtime dates
are in the past. Use `--no-cache` to skip the cache or `--clear` to delete it.
