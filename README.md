# 🍿 StreamGenie - Streaming Tracker (TMDB-powered)

A lightweight Streamlit app to **track streaming availability and next air dates** for TV shows across multiple streaming services.

## Features
- Search TV shows via TMDB
- Check if a show is available on **any streaming service** in your region (configurable in sidebar)
- Support for **Peacock, Netflix, Hulu, Prime Video, Disney+, Max, Apple TV+, Paramount+**, and many more
- Detect **next episode air date** (if announced in TMDB)
- Maintain a **local watchlist** in SQLite
- Track different providers for the same show simultaneously
- One-click **refresh** and **CSV export**

> **Note**: Streaming services don't have official public APIs. We use TMDB's "watch/providers" endpoint to infer availability by region. Accuracy depends on TMDB data.

## Quickstart

1. **Get a TMDB API key** (free): https://www.themoviedb.org/settings/api  
   - You can use a **v3 API key** or **v4 Read Access Token** (bearer).

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the app**:
   ```bash
   export TMDB_API_KEY="YOUR_TMDB_V3_KEY_OR_V4_BEARER"
   # optional:
   export TMDB_REGION="US"
   export DB_PATH="shows.db"
   streamlit run app.py
   ```

4. Open the local URL that Streamlit prints (usually http://localhost:8501).

## How it works
- **Search**: `/search/tv`
- **Details & next-air date**: `/tv/{id}` (uses `next_episode_to_air` when available), plus a fallback scan of season endpoints.
- **Providers**: `/tv/{id}/watch/providers` (searches for your configured streaming service in **any** provider list: flatrate, buy, rent, ads, free).

## Using Different Streaming Services

In the sidebar, you can change the **"Streaming service name"** field to track any provider supported by TMDB:

**Examples:**
- `Netflix`
- `Peacock`
- `Hulu`
- `Prime Video` or `Amazon Prime Video`
- `Disney Plus` or `Disney+`
- `Max` (formerly HBO Max)
- `Apple TV Plus` or `Apple TV+`
- `Paramount Plus` or `Paramount+`

You can track the same show on multiple services by adding it once for each provider.

## Caveats
- Availability may vary by **region** and **date**. Use the sidebar to set your ISO country code.
- Next-air dates depend on TMDB data completeness and may change.
- Provider names must match TMDB's naming convention (case-insensitive).

## Optional enhancements
- Add email/SMS notifications when a title becomes available or a new air date is announced.
- Deduplicate by title + year and add fuzzy search to handle remakes.
- Add bulk provider switching or comparison view.

---

Built for personal use and demos.