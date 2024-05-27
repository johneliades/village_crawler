import datetime
import os
import pickle
import sys
import requests
from itertools import groupby
from bs4 import BeautifulSoup
from imdb import Cinemagoer
import threading
import re
import json


class fg:
    blue = "\033[34m"
    cyan_bold = "\033[1;34m"
    red_bold = "\033[1;31m"
    cyan = "\033[96m"
    red = "\033[31m"
    green = "\033[32m"
    yellow = "\033[33m"
    grey = "\033[1;30m"
    clear_color = "\033[0m"
    bold = "\033[1m"

    def rgb(r, g, b):
        return f"\u001b[38;2;{r};{g};{b}m"


class bg:
    red = "\033[41m"
    green = "\033[42m"
    yellow = "\033[43m"

    def rgb(r, g, b):
        return f"\u001b[48;2;{r};{g};{b}m"


def crawl_village_titles(cinema_id):
    movie_dicts = []

    # s = requests.Session()

    # Send an HTTP GET request to the URL of the web page
    url = "https://www.villagecinemas.gr/en/tickets/film-choice"
    content = requests.get(url).content

    # File containing the response content
    file_path = "response_content.txt"

    # Read the content from the file
    with open(file_path, "rb") as file:
        content = file.read()

    # Assuming that you have the HTML content of the web page in a variable named 'html_content'
    village_soup = BeautifulSoup(content, "html.parser")

    pattern = re.compile(r"var bookingData = (\{.*?)</script>", re.DOTALL)
    matches = re.findall(pattern, str(village_soup))
    matches = matches[0]

    booking_data = json.loads(matches)

    for cinema in booking_data["filters"]["cinemas"]:
        if cinema_id == cinema["value"]:
            cinema_name = cinema["display"]
            columns, _ = os.get_terminal_size()
            print(cinema_name.center(columns))

    print()

    movies_showtimes = {}

    for screen in booking_data["screens"]:
        if cinema_id != screen["cinemaId"]:
            continue

        id = screen["id"]
        film_id = screen["scheduledFilmId"]
        showtime = datetime.datetime.strptime(screen["showtime"], "%Y-%m-%dT%H:%M:%S")
        screen_name = screen["screenName"]

        if film_id not in movies_showtimes:
            movies_showtimes[film_id] = {}

        # Extract days and hours
        day = showtime.strftime("%d/%m")
        hour = showtime.strftime("%H:%M")

        if day not in movies_showtimes[film_id]:
            movies_showtimes[film_id][day] = []

        availability = "available"

        # pload = {
        #     "filmId": film_id,
        #     "cinemaId": cinema_id,
        #     "date": showtime.strftime("%Y-%m-%d"),
        #     "recaptchaResponse": "",
        # }
        # content = s.post(
        #     "https://www.villagecinemas.gr/tickets/seat-availability", data=pload
        # )
        # seat_availability = json.loads(content.text)
        # print(seat_availability)
        # for cur in seat_availability["data"]["availability"]:
        #     if id == cur["screenId"]:
        #         if cur["isLimited"] == True:
        #             availability = "limited"
        #             break
        #         if cur["soldoutStatus"] == 1:
        #             availability = "not available"
        #             break

        movies_showtimes[film_id][day].append((hour, availability, screen_name))

    existing_titles = []
    for record in booking_data["records"]:
        if cinema_id not in record["cinemas"]:
            continue

        soup = BeautifulSoup(record["desc"], "html.parser")
        desc = soup.get_text(strip=True)

        title = record["title"]

        if title in existing_titles:
            continue

        existing_titles.append(title)

        print(f"{fg.yellow}[~]{fg.clear_color} Crawling Village: {title}", end="\r")

        days_to_hour_availability_screenName = {}

        for day in record["dates"]:
            day_obj = datetime.datetime.strptime(day, "%Y-%m-%d")
            day = day_obj.strftime("%d/%m")

            try:
                days_to_hour_availability_screenName[day] = movies_showtimes[
                    record["movieId"]
                ][day]
            except:
                pass

        movie_dict = {
            "id": record["movieId"],
            "title": title,
            "days": days_to_hour_availability_screenName,
            "village_plot": desc,
            "length": record["dur"],
            "village_url": record["url"],
            "trailer_url": (
                "https://www.youtube.com/watch?v=" + record["vid"]
                if record["vid"]
                else ""
            ),
        }
        movie_dicts.append(movie_dict)
        print(f"{fg.green}[✓]{fg.clear_color} Crawling Village: {title}")

    return movie_dicts


results_lock = threading.Lock()


def crawl_imdb_info(movie_dicts, index, imdb_api):
    title = movie_dicts[index]["title"]
    # Search for the movie by name
    try:
        movies = imdb_api.search_movie(title)
        movie = imdb_api.get_movie(movies[0].getID())

        url_imdb = imdb_api.get_imdbURL(movie)

        # Get the IMDb rating of the movie
        imdb_api.update(movie)
        rating = movie.get("rating")

        plot = movie.data.get("plot outline")
        if not plot:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
            }

            response_imdb = requests.get(url_imdb, headers=headers)
            soup_imdb = BeautifulSoup(response_imdb.text, "html.parser")
            plot_elem = soup_imdb.find("p", {"data-testid": "plot"})
            first_span = plot_elem.find("span", recursive=False)
            plot = first_span.text.strip()

        movie_dicts[index]["imdb_plot"] = plot
    except:
        movie_dicts[index]["imdb_rating"] = "?"
        movie_dicts[index]["imdb_url"] = "?"
        return

    # Rating not found in imdb or greek movie that doesn't appear in imdb results
    if rating == None or any(ord(char) in set(range(0x0370, 0x0400)) for char in title):
        rating = "?"

    print(f"{fg.green}[✓]{fg.clear_color} Crawled IMDB: {movie_dicts[index]['title']}")

    with results_lock:
        movie_dicts[index]["imdb_rating"] = rating
        movie_dicts[index]["imdb_url"] = url_imdb


def print_movies(sorted_movies, search_day):
    columns, _ = os.get_terminal_size()

    print()

    print(fg.green)
    print("┌──────────────────┬───────────┐  ".center(columns))
    print("│   normal cost    │ what's up │  ".center(columns))
    print("│─────────┬────────┼───────────│  ".center(columns))
    print("│ classic │  9,5 € │   6,65 €  │  ".center(columns))
    print("│  dolby  │ 10,5 € │   7,35 €  │  ".center(columns))
    print("│   vmax  │ 12,0 € │   8,40 €  │  ".center(columns))
    print("│   gold  │ 24,5 € │           │  ".center(columns))
    print("└─────────┴────────┴───────────┘  ".center(columns))
    print(fg.clear_color)

    date_time = datetime.datetime.now()
    today = date_time.strftime("%d/%m")

    no_longer_playing_today = 0

    for movie in sorted_movies:
        movie_start_times = []
        movie_end_times = []
        movie_availabilities = []
        movie_classes = []
        if movie["length"] != None:
            delta = datetime.timedelta(minutes=int(movie["length"]))
        else:
            delta = None

        for index, time_tuple in enumerate(movie["days"][search_day]):
            time, availability, class_type = time_tuple

            formated_time = datetime.datetime.strptime(time, "%H:%M")
            if delta != None:
                end_time = formated_time + delta

            if search_day == today and formated_time.time() > date_time.now().time():
                movie_start_times.append(time)
                if delta != None:
                    movie_end_times.append(end_time.strftime("%H:%M"))
            elif search_day == today and formated_time.time() < date_time.now().time():
                if index == len(movie["days"][search_day]) - 1:
                    no_longer_playing_today += 1
                continue
            elif search_day != today:
                movie_start_times.append(time)
                if delta != None:
                    movie_end_times.append(end_time.strftime("%H:%M"))

            if availability == "available":
                movie_availabilities.append(bg.green)
            elif availability == "limited":
                movie_availabilities.append(bg.yellow)
            elif availability == "not available":
                movie_availabilities.append(bg.red)

            if "ΑΙΘ" in class_type:
                movie_classes.append("")
            elif "VMax" in class_type:
                movie_classes.append(fg.green + "vmax " + fg.clear_color)
            elif "GOLD" in class_type:
                movie_classes.append(fg.yellow + "gold " + fg.clear_color)

        if len(movie_start_times) == 0:
            continue

        columns, _ = os.get_terminal_size()

        if movie["imdb_rating"] == "?":
            color = fg.red
        elif float(movie["imdb_rating"]) >= 7:
            color = fg.green
        elif float(movie["imdb_rating"]) >= 6 and movie["imdb_rating"] < 7:
            color = fg.yellow
        else:
            color = fg.red

        half_width = columns - len(movie["title"]) - 5 - len(str(movie["imdb_rating"]))

        print(fg.cyan, end="")
        for i in range(half_width // 2):
            print("\u2501", end="")
        print(
            " "
            + movie["title"]
            + " ("
            + color
            + str(movie["imdb_rating"])
            + fg.cyan
            + ") ",
            end="",
        )
        for i in range(half_width // 2):
            print("\u2501", end="")
        print(fg.clear_color)

        formatted_times = []
        if delta != None:
            lists = [
                movie_start_times,
                movie_end_times,
                movie_availabilities,
                movie_classes,
            ]
            for start, end, availability, movie_class in zip(*lists):
                formatted_times.append(
                    f"{availability} {fg.clear_color} {movie_class}"
                    f"{fg.cyan_bold}{start}{fg.clear_color}-"
                    f"{fg.red_bold}{end}{fg.clear_color}"
                )
        else:
            lists = [movie_start_times, movie_availabilities, movie_classes]
            for start, availability, movie_class in zip(*lists):
                formatted_times.append(
                    f"{availability} {fg.clear_color} {movie_class}"
                    f"{fg.cyan_bold}{start}{fg.clear_color}"
                )

        # print(fg.grey + movie["imdb_url"].center(columns) + fg.clear_color)
        print(
            (
                fg.grey
                + movie["village_url"]
                + (", " + movie["trailer_url"] if movie["trailer_url"] else "")
                + fg.clear_color
                + "\n"
            ).center(columns + len(fg.grey) + len(fg.clear_color) + 3),
        )

        result = " "
        result += ", ".join(formatted_times)
        visible_length = len(result) - (result.count("\033[") * 5) - 2
        padding = " " * ((columns - visible_length) // 2)

        print(padding + result + "\n")

        formatted_availabilities = []

        print(movie["village_plot"].center(columns))

        print()

    if no_longer_playing_today == len(sorted_movies):
        print("No more movies today".center(columns))


def main():
    mall_code = "21"
    renti_code = "01"

    data_path = "data.pkl"

    if "clear" in sys.argv and os.path.exists(data_path):
        result = input("Are you sure you want to remove data?")

        os.remove(data_path)

    old_movies = False
    if os.path.exists(data_path):
        print()
        print("Loading previous database, ticket availability may be outdated.")
        print("Rerun with the 'clear' argument to refresh the data.")
        with open(data_path, "rb") as pkl_handle:
            sorted_movies = pickle.load(pkl_handle)

            movie_days = []
            for movie in sorted_movies:
                for day in list(movie["days"].keys()):
                    day, month = map(int, day.split("/"))
                    current_year = datetime.datetime.now().year
                    day_obj = datetime.datetime(current_year, month, day)
                    movie_days.append(day_obj)

            movie_days = list(set(movie_days))
            movie_days.sort()

            date_time = datetime.datetime.now()
            today = date_time.strftime("%d/%m")

            day, month = map(int, today.split("/"))
            current_year = datetime.datetime.now().year
            today_datetime = datetime.datetime(current_year, month, day)

            if len(sorted_movies) == 0 or all(
                [today_datetime.date() > day.date() for day in movie_days]
            ):
                os.remove(data_path)
                old_movies = True

    if not os.path.exists(data_path) or old_movies:
        # Create an instance of the IMDb class
        imdb_api = Cinemagoer()

        movie_dicts = crawl_village_titles(mall_code)

        # Create and start threads
        threads = []
        for i in range(len(movie_dicts)):
            thread = threading.Thread(
                target=crawl_imdb_info, args=(movie_dicts, i, imdb_api)
            )
            thread.start()
            threads.append(thread)

        # Wait for all threads to finish
        for thread in threads:
            thread.join()

        filtered_movies = [movie for movie in movie_dicts if movie["length"] != "?"]

        sorted_movies = sorted(
            filtered_movies,
            key=lambda m: m["imdb_rating"] if m["imdb_rating"] != "?" else 0,
            reverse=True,
        )

        with open(data_path, "wb") as pkl_handle:
            pickle.dump(sorted_movies, pkl_handle)

    date_time = datetime.datetime.now()
    search_day = date_time.strftime("%d/%m")

    if len(sys.argv) == 2 and sys.argv[1] != "clear":
        search_day = sys.argv[1]

    sorted_movies = [
        movie for movie in sorted_movies if search_day in movie["days"].keys()
    ]

    print_movies(sorted_movies, search_day)


if __name__ == "__main__":
    main()
