import asyncio
import os
import requests
from telethon import TelegramClient, events
from pymongo import MongoClient
from telethon.tl.custom import Button
from dotenv import load_dotenv


load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Initialize MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['movie_bot']
collection = db['user_preferences']

# Initialize Telethon client
client = TelegramClient('movie_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# TMDb API endpoints
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"


def get_keyword_id(keyword):
    """Fetch the TMDb keyword ID for a given keyword."""
    url = f"{TMDB_BASE_URL}/search/keyword"
    params = {"api_key": TMDB_API_KEY, "query": keyword}
    response = requests.get(url, params=params)

    if response.status_code == 200:
        results = response.json().get("results", [])
        if results:
            return results[0]["id"]  # Return the first matching keyword ID
    return None

def get_movie_recommendations(genre_ids=None, language="en", keywords=None, min_movies=15):
    """Fetch movie recommendations from TMDb with fallback logic."""
    print("Fetching movie recommendations...")
    print("genre_ids:", genre_ids)
    print("language:", language)
    print("keywords:", keywords)

    url = f"{TMDB_BASE_URL}/discover/movie"
    
    # Convert keyword names to IDs
    keyword_ids = [str(get_keyword_id(k)) for k in keywords if get_keyword_id(k)] if keywords else []
    def fetch_movies(genres, keywords , page):
        genres.remove(445) if 445 in genres else None
        params = {
            "api_key": TMDB_API_KEY,
            "language": language,
            "sort_by": "popularity.desc",
            "include_adult": True,
            "include_video": False,
            "page": page,
            "with_genres": ",".join(map(str, genres)) if genres else None,
            "with_keywords": ",".join(keywords) if keywords else None,
        }

        response = requests.get(url, params=params)
        print(response.status_code)
        if response.status_code == 200:
            return response.json().get("results", [])
        
        return []
    all_movies = []
    page = 1
    while True:
        result = fetch_movies(genre_ids, keyword_ids , page)
        all_movies.extend(result)
        if len(all_movies) >= min_movies:
            break
        if result:
            page += 1
        keyword_ids.pop(0) if keyword_ids else genre_ids.pop(0) if genre_ids else None
        if not genre_ids and not keyword_ids:
            break
    print(len(all_movies))
    return all_movies


def format_movie_message(movie):
    """Format movie data into a readable message."""
    title = movie.get('title', 'Unknown Title')
    overview = movie.get('overview', 'No overview available.')
    release_date = movie.get('release_date', 'Unknown Release Date')
    poster_path = movie.get('poster_path')
    poster_url = f"{TMDB_IMAGE_URL}{poster_path}" if poster_path else None

    message = f"🎬 **{title}**\n"
    message += f"📅 **Release Date:** {release_date}\n"
    message += f"📝 **Overview:** {overview}\n"
    if poster_url:
        message += f"🎞️ [Poster]({poster_url})\n"
    return message


@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    """Send a welcome message."""
    await event.respond(
        "Welcome to the Movie Recommendation Bot! 🎥\n\n"
        "Use /setpreferences to set your favorite genres and language.\n"
        "Use /recommend to get movie recommendations."
    )


GENRES = {
    "Action": 28, "Adventure": 12, "Adult": 445 , "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Science Fiction": 878,
    "TV Movie": 10770, "Thriller": 53, "War": 10752, "Western": 37,
}

@client.on(events.NewMessage(pattern='/setpreferences'))
async def set_preferences(event):
    """Set user preferences for genres and language."""
    user_id = event.sender_id
    user_preferences = collection.find_one({"user_id": user_id})
    favorite_genres = user_preferences.get("favorite_genres", []) if user_preferences else []

    def get_button_label(genre, genre_id):
        return f"{genre} {'✅' if genre_id in favorite_genres else '❌'}"

    async with client.conversation(user_id) as conv:
        while True:
            # Generate buttons with ✅ and ❌ indicators
            buttons = [
                [Button.inline(get_button_label(genre, genre_id), data=str(genre_id)) 
                 for genre, genre_id in list(GENRES.items())[i:i+3]]
                for i in range(0, len(GENRES), 3)
            ]
            buttons.append([Button.inline("Done ✅", data="done")])

            # Send the interactive message
            msg = await conv.send_message("Select your favorite genres:", buttons=buttons)

            while True:
                try:
                    # Wait for user interaction with a timeout of 60 seconds
                    response = await conv.wait_event(events.CallbackQuery, timeout=60)
                    data = response.data.decode("utf-8")

                    if data == "done":
                        # Save preferences to MongoDB
                        collection.update_one(
                            {"user_id": user_id},
                            {"$set": {"favorite_genres": favorite_genres}},
                            upsert=True
                        )
                        break

                    genre_id = int(data)
                    if genre_id in favorite_genres:
                        favorite_genres.remove(genre_id)
                        await response.answer("Removed from favorites", alert=True)
                    else:
                        favorite_genres.append(genre_id)
                        await response.answer("Added to favorites", alert=True)

                    # Update button labels and refresh message
                    buttons = [
                        [Button.inline(get_button_label(genre, genre_id), data=str(genre_id)) 
                         for genre, genre_id in list(GENRES.items())[i:i+3]]
                        for i in range(0, len(GENRES), 3)
                    ]
                    buttons.append([Button.inline("Done ✅", data="done")])

                    await msg.edit("Select your favorite genres:", buttons=buttons)

                except asyncio.TimeoutError:
                    # Handle timeout (e.g., send a reminder or reset the conversation)
                    await conv.send_message("You took too long to respond. Please try again.")
                    return  # Exit the function or restart the conversation
            try:
                # Save language preference to MongoDB
                collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"preferred_language": "en"}},
                    upsert=True
                )

                await event.respond("✅ Preferences saved!")
                await event.respond(
        "Use /setpreferences to set your favorite genres and language.\n"
        "Use /recommend to get movie recommendations."
    )
                return
            except asyncio.TimeoutError:
                await conv.send_message("You took too long to respond. Please try again.")
                return  # Exit the function or restart the conversation


@client.on(events.NewMessage(pattern='/recommend'))
async def recommend_movies(event):
    """Send movie recommendations based on user preferences."""
    user_id = event.sender_id
    user_preferences = collection.find_one({"user_id": user_id})

    if not user_preferences:
        await event.respond("Please set your preferences using /setpreferences first.")
        return

    # Fetch movie recommendations
    genre_ids = user_preferences.get("favorite_genres", [])
    movies = get_movie_recommendations(genre_ids=genre_ids, keywords=["erotic"] if 445 in genre_ids else [] , min_movies = 20)
    if not movies:
        await event.respond("No recommendations found. Try updating your preferences.")
        return

    # Send the first 5 recommendations
    for movie in movies[:20]:
        await event.respond(format_movie_message(movie))
    await event.respond(
        "Use /setpreferences to set your favorite genres and language.\n"
        "Use /recommend to get movie recommendations."
    )

# Run the bot
print("Bot is running...")
client.run_until_disconnected()
