from __future__ import annotations

from typing import Optional, List
from random import Random
from datetime import date

from sotd.auth import get_spotify_client, get_catalog_client
from sotd.profile import get_user_profile
from sotd.candidates import generate_candidates, filter_candidates_by_mood


def _pick_one(track_ids: List[str]) -> Optional[str]:
    if not track_ids:
        return None
    # Deterministic daily pick based on date for consistency
    rng = Random(date.today().isoformat())
    return rng.choice(track_ids)


def song_of_the_day(sp, mood: Optional[str] = None) -> None:
    """
    Build user profile, generate candidates, apply optional mood filtering, pick one, and print details.
    """
    profile = get_user_profile(sp)
    candidates = generate_candidates(sp, profile)

    if not candidates:
        print("No candidates found today. Try again later or widen your listening history.")
        return

    filtered = filter_candidates_by_mood(candidates, mood=mood) if mood else candidates
    track_id = _pick_one(filtered) or _pick_one(candidates)

    if not track_id:
        print("No recommendation could be made today. Please try again later.")
        return

    # Use catalog client to fetch track details
    cat = get_catalog_client()
    track = cat.track(track_id)
    name = track.get("name")
    artists = ", ".join(a.get("name") for a in (track.get("artists") or []))
    url = f"https://open.spotify.com/track/{track_id}"

    if mood:
        print(f"Song of the Day [{mood}]: {name} — {artists} \n{url}")
    else:
        print(f"Song of the Day: {name} — {artists} \n{url}")


if __name__ == "__main__":
    sp = get_spotify_client()
    # Example invocation for testing; change mood as desired
    song_of_the_day(sp, mood="Happy")
