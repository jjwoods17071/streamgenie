"""
Production Intelligence Module
Enhanced show status tracking with web search and AI analysis
Helps distinguish between dead shows vs shows in production
"""
import os
import requests
from typing import Optional, Dict, Tuple
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"


def get_enhanced_status(
    show_title: str,
    tmdb_id: int,
    tmdb_data: Dict,
    use_web_search: bool = False
) -> Dict:
    """
    Get enhanced production status for a show

    Args:
        show_title: Show title
        tmdb_id: TMDB show ID
        tmdb_data: Data from TMDB API (from show_status.fetch_show_status)
        use_web_search: Whether to use web search for additional intel

    Returns:
        Dictionary with enhanced status information
    """
    status = tmdb_data.get("status", "Unknown")
    in_production = tmdb_data.get("in_production", False)
    next_episode = tmdb_data.get("next_episode_to_air")
    last_air_date = tmdb_data.get("last_air_date")
    last_episode = tmdb_data.get("last_episode_to_air")

    # Determine status category
    category, confidence, message = _categorize_status(
        status=status,
        in_production=in_production,
        next_episode=next_episode,
        last_air_date=last_air_date,
        last_episode=last_episode,
        show_title=show_title
    )

    result = {
        "category": category,  # One of the emoji categories
        "confidence": confidence,  # "high", "medium", "low"
        "message": message,  # Human-readable status message
        "tmdb_status": status,
        "in_production": in_production,
        "has_next_episode": next_episode is not None,
        "last_air_date": last_air_date,
        "needs_research": confidence == "low" and status not in ["Ended", "Canceled"]
    }

    # If confidence is low and show might still be active, optionally search web
    if use_web_search and result["needs_research"]:
        web_intel = _search_production_news(show_title, tmdb_data)
        if web_intel:
            result["web_intel"] = web_intel
            result["message"] = f"{message}\n\n{web_intel}"

    return result


def _categorize_status(
    status: str,
    in_production: bool,
    next_episode: Optional[Dict],
    last_air_date: Optional[str],
    last_episode: Optional[Dict],
    show_title: str
) -> Tuple[str, str, str]:
    """
    Categorize show status into clear categories

    Returns:
        Tuple of (category_emoji, confidence_level, message)
    """
    # ENDED - Clear case
    if status == "Ended":
        if last_air_date:
            return ("ENDED", "high", f"Series concluded. Final episode aired {_format_date(last_air_date)}.")
        return ("ENDED", "high", "Series has concluded.")

    # CANCELED - Clear case
    if status == "Canceled":
        if last_air_date:
            return ("CANCELED", "high", f"Canceled. Last episode aired {_format_date(last_air_date)}.")
        return ("CANCELED", "high", "Show has been canceled.")

    # HAS SCHEDULED EPISODE - Clear case
    if next_episode:
        air_date = next_episode.get("air_date")
        season = next_episode.get("season_number")
        episode = next_episode.get("episode_number")

        if air_date:
            formatted_date = _format_date(air_date)
            return (
                "SCHEDULED",
                "high",
                f"Next episode: S{season}E{episode} on {formatted_date}"
            )

    # IN PRODUCTION - High confidence
    if in_production and status == "Returning Series":
        return (
            "IN PRODUCTION",
            "high",
            "Currently in production. New season confirmed but air date not announced."
        )

    # RETURNING SERIES - but not in production
    if status == "Returning Series":
        if last_air_date:
            years_since = _years_since(last_air_date)

            if years_since < 1:
                return (
                    "RETURNING SOON",
                    "medium",
                    f"Show is active. Last aired {_format_date(last_air_date)}. New season expected."
                )
            elif years_since < 3:
                return (
                    "UNCERTAIN",
                    "low",
                    f"Marked as returning series, but last aired {_format_date(last_air_date)} ({years_since:.0f} years ago). Status unclear."
                )
            else:
                return (
                    "ON HIATUS",
                    "low",
                    f"On extended hiatus. Last aired {_format_date(last_air_date)} ({years_since:.0f} years ago)."
                )

        return ("RETURNING SOON", "medium", "Marked as returning series. No air date announced.")

    # IN PRODUCTION - but status is unclear
    if in_production:
        return (
            "IN PRODUCTION",
            "medium",
            "Currently in production. Status and air date to be confirmed."
        )

    # PLANNED
    if status == "Planned":
        return (
            "RENEWED",
            "medium",
            "Show has been renewed. Production has not yet started."
        )

    # PILOT
    if status == "Pilot":
        return (
            "PILOT",
            "high",
            "Pilot episode available. Series pickup not yet confirmed."
        )

    # OLD SHOW - Legacy content
    if last_air_date:
        years_since = _years_since(last_air_date)

        if years_since > 10:
            return (
                "LEGACY",
                "high",
                f"Classic show. Last aired {_format_date(last_air_date)} ({years_since:.0f} years ago). No new episodes expected."
            )
        elif years_since > 5:
            return (
                "ON HIATUS",
                "medium",
                f"On extended hiatus. Last aired {_format_date(last_air_date)} ({years_since:.0f} years ago)."
            )

    # UNKNOWN - Fallback
    return (
        "UNCERTAIN",
        "low",
        "Status uncertain. Check TMDB or search online for production news."
    )


def _search_production_news(show_title: str, tmdb_data: Dict) -> Optional[str]:
    """
    Search web for production news about the show

    Args:
        show_title: Show title
        tmdb_data: TMDB data for context

    Returns:
        String with production intel or None
    """
    # This would integrate with Claude's WebSearch tool
    # For now, return None - will be implemented when integrated with app.py
    # The app.py integration will call WebSearch and pass results here
    return None


def _format_date(date_str: str) -> str:
    """Format date string to human-readable format"""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        return date_obj.strftime("%B %d, %Y")
    except Exception:
        return date_str


def _years_since(date_str: str) -> float:
    """Calculate years since a date"""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = date.today()
        delta = today - date_obj
        return delta.days / 365.25
    except Exception:
        return 0.0


def get_production_search_query(show_title: str, current_season: int) -> str:
    """
    Generate optimized search query for production news

    Args:
        show_title: Show title
        current_season: Current season number

    Returns:
        Search query string
    """
    next_season = current_season + 1
    current_year = datetime.now().year

    return f'"{show_title}" season {next_season} production filming release date {current_year} {current_year + 1}'


def parse_web_search_results(search_results: str, show_title: str) -> Dict:
    """
    Parse web search results to extract production intel

    Args:
        search_results: Raw search results text
        show_title: Show title for context

    Returns:
        Dictionary with extracted intel
    """
    # Keywords to look for
    positive_keywords = [
        "renewed", "filming", "production", "scheduled", "confirmed",
        "greenlit", "announced", "in development", "pre-production",
        "shooting", "principal photography", "wrapping", "post-production"
    ]

    negative_keywords = [
        "canceled", "cancelled", "axed", "not renewed", "no season",
        "final season", "series finale", "concluded", "ended"
    ]

    timing_keywords = {
        "2024": 2024, "2025": 2025, "2026": 2026,
        "this year": datetime.now().year,
        "next year": datetime.now().year + 1,
        "spring": "Spring", "summer": "Summer", "fall": "Fall", "winter": "Winter",
        "Q1": "Q1", "Q2": "Q2", "Q3": "Q3", "Q4": "Q4"
    }

    search_lower = search_results.lower()

    # Check for positive signals
    found_positive = [kw for kw in positive_keywords if kw in search_lower]
    found_negative = [kw for kw in negative_keywords if kw in search_lower]
    found_timing = [kw for kw in timing_keywords if kw in search_lower]

    intel = {
        "has_positive_signals": len(found_positive) > 0,
        "has_negative_signals": len(found_negative) > 0,
        "positive_keywords": found_positive,
        "negative_keywords": found_negative,
        "timing_mentions": found_timing,
        "confidence": "unknown"
    }

    # Determine confidence
    if found_negative:
        intel["confidence"] = "negative"
        intel["summary"] = f"Web sources suggest {show_title} may not return. Keywords: {', '.join(found_negative[:3])}"
    elif found_positive and found_timing:
        intel["confidence"] = "high"
        intel["summary"] = f"Web sources indicate {show_title} is in active development. Keywords: {', '.join(found_positive[:3])}"
    elif found_positive:
        intel["confidence"] = "medium"
        intel["summary"] = f"Some production activity found, but timeline unclear. Keywords: {', '.join(found_positive[:3])}"
    else:
        intel["confidence"] = "low"
        intel["summary"] = "No clear production news found in recent web sources."

    return intel


def get_status_emoji(category: str) -> str:
    """Get just the emoji from a category string"""
    if not category:
        return "❓"

    # Extract emoji (first part before space)
    parts = category.split()
    return parts[0] if parts else "❓"


def get_status_color(category: str) -> str:
    """Get color for status badge"""
    category_lower = category.lower()

    if "production" in category_lower or "scheduled" in category_lower:
        return "green"
    elif "renewed" in category_lower or "returning" in category_lower:
        return "blue"
    elif "uncertain" in category_lower or "hiatus" in category_lower:
        return "orange"
    elif "ended" in category_lower or "canceled" in category_lower or "legacy" in category_lower:
        return "red"
    else:
        return "gray"
