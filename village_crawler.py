import datetime
import os
import pickle
import sys
import requests
from itertools import groupby
from bs4 import BeautifulSoup
from imdb import Cinemagoer
import threading


class fg:
    blue = "\033[1;34m"
    light_red = "\033[1;31m"
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


def crawl_village_titles():
    mall_code = "21"
    renti_code = "01"

    movie_dicts = []

    # Send an HTTP GET request to the URL of the web page
    url = "https://www.villagecinemas.gr/WebTicketing/?CinemaCode=" + mall_code
    response = requests.get(url)

    # Assuming that you have the HTML content of the web page in a variable named 'html_content'
    village_soup = BeautifulSoup(response.content, "html.parser")

    # Select all elements with a "data-vc-movie" attribute that contains data
    elements = village_soup.select("[data-vc-movie]")

    # Extract and store the second media-heading(the english movie name)
    # and the data-vc-movie(the movie code) for each element
    for element in elements:
        second_media_heading = element.select_one(".media-heading:nth-of-type(2)")
        if second_media_heading is not None:
            title = second_media_heading.text
        else:
            title = element.select_one(".media-heading:nth-of-type(1)").text

        print(f"{fg.yellow}[~]{fg.clear_color} Crawling Village: {title}", end="\r")

        movie_code = element.get("data-vc-movie")

        movie_response = requests.get(url + "&MovieCode=" + movie_code)
        movie_soup = BeautifulSoup(movie_response.content, "html.parser")

        days_hours_dict = {}
        hours = movie_soup.select(".str-time")
        class_types = movie_soup.select(".type-item")
        availability = movie_soup.select(".availability")

        lists = [hours, availability, class_types]
        for hour, available, class_type in zip(*lists):
            key = hour.parent.parent.parent.get("id").replace("timeof", "")

            date_obj = datetime.datetime.strptime(key, "%Y%m%d")
            day = date_obj.strftime("%d/%m")

            if day not in days_hours_dict:
                days_hours_dict[day] = []
            days_hours_dict[day].append(
                (hour.text, available["class"][1], class_type.text)
            )

        movie_dict = {"title": title, "days": days_hours_dict}
        movie_dicts.append(movie_dict)
        print(f"{fg.green}[✓]{fg.clear_color} Crawling Village: {title}")

    return movie_dicts


def crawl_imdb_info(title, imdb_api):
    # Search for the movie by name
    try:
        movies = imdb_api.search_movie(title)
        movie = imdb_api.get_movie(movies[0].getID())

        # Get the IMDb rating of the movie
        imdb_api.update(movie)
        rating = movie.get("rating")
        plot = movie.data.get("plot outline")
        length_minutes = movie.get("runtimes")[0] if movie.get("runtimes") else None
    except:
        return None

    # Rating not found in imdb or greek movie that doesn't appear in imdb results
    if rating == None or any(ord(char) in set(range(0x0370, 0x0400)) for char in title):
        rating = "?"
        plot = "?"

    # Sometimes the library doesn't return the plot so I take it manually
    # from the actual imdb site using the url the library returns
    url_imdb = imdb_api.get_imdbURL(movie)

    if plot == None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
            AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
        }

        response_imdb = requests.get(url_imdb, headers=headers)
        soup_imdb = BeautifulSoup(response_imdb.text, "html.parser")
        plot_elem = soup_imdb.find("p", {"data-testid": "plot"})
        first_span = plot_elem.find("span", recursive=False)
        plot = first_span.text.strip()
        if plot is None:
            plot = "?"

    return rating, plot, length_minutes, url_imdb


results_lock = threading.Lock()


def fetch_movie_info(movie_dict, imdb_api, movies_list):
    result = crawl_imdb_info(movie_dict["title"], imdb_api)
    print(f"{fg.green}[✓]{fg.clear_color} Crawled IMDB: {movie_dict['title']}")

    if result == None:
        return

    rating, plot, length_minutes, url_imdb = result

    movie_dict["imdb"] = rating
    movie_dict["plot"] = plot
    movie_dict["length"] = length_minutes
    movie_dict["url"] = url_imdb

    with results_lock:
        movies_list.append(movie_dict)


def print_movies(sorted_movies, search_day):
    columns, _ = os.get_terminal_size()

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

    for movie in sorted_movies:
        movie_start_times = []
        movie_end_times = []
        movie_availabilities = []
        movie_classes = []
        if movie["length"] != None:
            delta = datetime.timedelta(minutes=int(movie["length"]) + 14)
        else:
            delta = None

        for time_tuple in movie["days"][search_day]:
            time, availability, class_type = time_tuple

            formated_time = datetime.datetime.strptime(time, "%H:%M")
            if delta != None:
                end_time = formated_time + delta

            if search_day == today and formated_time.time() > date_time.now().time():
                movie_start_times.append(time)
                if delta != None:
                    movie_end_times.append(end_time.strftime("%H:%M"))
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

        if movie["imdb"] == "?":
            color = fg.red
        elif float(movie["imdb"]) >= 7:
            color = fg.green
        elif float(movie["imdb"]) >= 6 and movie["imdb"] < 7:
            color = fg.yellow
        else:
            color = fg.red

        half_width = columns - len(movie["title"]) - 5 - len(str(movie["imdb"]))

        print(fg.cyan, end="")
        for i in range(half_width // 2):
            print("\u2501", end="")
        print(
            " " + movie["title"] + " (" + color + str(movie["imdb"]) + fg.cyan + ") ",
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
                    f"{fg.blue}{start}{fg.clear_color}-"
                    f"{fg.light_red}{end}{fg.clear_color}"
                )
        else:
            lists = [movie_start_times, movie_availabilities, movie_classes]
            for start, availability, movie_class in zip(*lists):
                formatted_times.append(
                    f"{availability} {fg.clear_color} {movie_class}"
                    f"{fg.blue}{start}{fg.clear_color}"
                )

        print(fg.grey + movie["url"].center(columns) + fg.clear_color + "\n")

        result = " "
        result += ", ".join(formatted_times)
        visible_length = len(result) - (result.count("\033[") * 5) - 2
        padding = " " * ((columns - visible_length) // 2)

        print(padding + result + "\n")

        formatted_availabilities = []

        if movie["plot"] != "?":
            print(movie["plot"].center(columns))

        print()


def main():
    data_path = "data.pkl"

    if "clear" in sys.argv and os.path.exists(data_path):
        result = input("Are you sure you want to remove data?")

        os.remove(data_path)

    old_movies = False
    if os.path.exists(data_path):
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

        # Create a list to store the extracted data
        movies_list = []

        movie_dicts = crawl_village_titles()

        # Create a list to store the results
        movies_list = []

        # Create and start threads
        threads = []
        for movie_dict in movie_dicts:
            thread = threading.Thread(
                target=fetch_movie_info, args=(movie_dict, imdb_api, movies_list)
            )
            thread.start()
            threads.append(thread)

        # Wait for all threads to finish
        for thread in threads:
            thread.join()

        sorted_movies = sorted(
            movies_list,
            key=lambda m: m["imdb"] if m["imdb"] != "?" else 0,
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

    # Removes the movies that already exist but with some suffix like dolby atmos
    # sorted_movies = [
    #     movie
    #     for movie in sorted_movies
    #     if all(
    #         other["title"] not in movie["title"]
    #         for other in sorted_movies
    #         if movie["title"] != other["title"]
    #     )
    # ]

    # Merges the movies that exist both in gr and eng
    # merged_movies = []
    # for key, group in groupby(sorted_movies, key=lambda movie: movie['title'].replace("(ENG)", "").replace("(GR)", "").strip()):
    #     group = list(group)
    #     if len(group) == 2:
    #         group = group[0]
    #         merged_title = f"{key} (ENG-GR)"
    #         merged_movies.append({"title": merged_title, 'days': group['days'],
    #             'imdb': group['imdb'], 'plot': group['plot'], "length": group['length'], "url": group['url']})
    #     else:
    #         merged_movies.extend(group)

    # sorted_movies = merged_movies

    print_movies(sorted_movies, search_day)


if __name__ == "__main__":
    main()
