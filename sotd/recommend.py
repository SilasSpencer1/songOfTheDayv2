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
    rng = Random(date.today().isoformat())
    return rng.choice(track_ids)


def song_of_the_day(sp, mood: Optional[str] = None) -> None:
    profile = get_user_profile(sp)

    # Build candidates and enforce strict novelty
    candidates = generate_candidates(sp, profile)
    candidates = [tid for tid in candidates if tid not in profile.get("known_tracks", set())]

    # Apply mood if provided; take top 10 after mood ranking
    if mood:
        ranked = filter_candidates_by_mood(candidates, mood=mood, top_k=10)
    else:
        ranked = candidates[:10]

    track_id = _pick_one(ranked) or _pick_one(candidates)
    if not track_id:
        print("No recommendation could be made today. Please try again later.")
        return

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
