from __future__ import annotations

from typing import Dict, List, Set, Tuple

# Curated mood-to-genre mapping (expand as needed)
MOOD_GENRES: Dict[str, List[str]] = {
    "happy": [
        "pop",
        "indie pop",
        "dance pop",
        "funk",
        "disco",
        "nu-disco",
        "tropical house",
        "soul",
    ],
    "sad": [
        "indie folk",
        "acoustic",
        "singer-songwriter",
        "ambient pop",
        "slowcore",
        "sad rap",
        "emo rap",
        "melancholia",
    ],
    "energetic": [
        "edm",
        "house",
        "techno",
        "drum and bass",
        "rock",
        "garage rock",
        "hyperpop",
        "dance rock",
    ],
    "angry": [
        "metal",
        "metalcore",
        "hard rock",
        "punk",
        "trap metal",
    ],
    "calm": [
        "lo-fi beats",
        "chillhop",
        "ambient",
        "neo-classical",
        "soft rock",
        "bossa nova",
        "chillout",
        "jazz",
    ],
}

# Popularity and recency preferences per mood (0..1 target)
POPULARITY_TARGET: Dict[str, float] = {
    "happy": 0.75,
    "energetic": 0.75,
    "angry": 0.6,
    "calm": 0.5,
    "sad": 0.45,
}

RECENCY_BIAS_YEARS: Dict[str, int] = {
    "happy": 3,
    "energetic": 3,
    "angry": 5,
    "calm": 15,
    "sad": 10,
}


def mood_genres(mood: str) -> Set[str]:
    return set(MOOD_GENRES.get(mood.lower(), []))


__all__ = ["MOOD_GENRES", "mood_genres", "POPULARITY_TARGET", "RECENCY_BIAS_YEARS"]
