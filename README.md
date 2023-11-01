# village_crawler
 
After reverse engineering the village cinemas WebTicketing API, I made 
this python script that retrieves a list of currently playing movies 
and the ticket availability and showtimes. It then fetches additional 
information such as the plot and rating from IMDb, sorts them according
to rating and presents them in an appealing and user-friendly manner.

<p align="center">
  <img src="https://github.com/johneliades/village_crawler/blob/main/preview.jpg" alt="animated" />
</p>


## Clone

Clone the repository locally by entering the following command:
```
git clone https://github.com/johneliades/village_crawler.git
```
Or by clicking on the green "Clone or download" button on top and then 
decompressing the zip.

Then install the missing libraries in a virtual environment:

```
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && deactivate
```

## Run

Then you can run:

```
.venv\Scripts\activate
python village_crawler.py
```
