from __future__ import annotations

from typing import Any, Dict, List, Set
from collections import Counter


def _extract_artist_ids(artists: List[dict]) -> List[str]:
    return [a.get("id") for a in artists if a and a.get("id")]


def _extract_artist_names(artists: List[dict]) -> List[str]:
    return [a.get("name") for a in artists if a and a.get("name")]


def get_user_profile(
    sp: Any,
    *,
    top_artists_limit: int = 10,
    top_tracks_limit: int = 20,
    recently_played_limit: int = 50,
    saved_tracks_limit: int = 50,
    time_range: str = "short_term",
) -> Dict[str, Any]:
    """
    Retrieve user's listening data and return a consolidated profile.

    Returns a dictionary with:
      - top_artists: List[{"id", "name", "genres"}]
      - top_tracks: List[{"id", "name", "artist_ids", "artist_names"}]
      - recent_tracks: List[{"id", "name", "artist_ids", "artist_names", "played_at"}]
      - known_artists: Set[str]
      - known_tracks: Set[str]
      - top_artist_genres: List[str] (genres aggregated from top_artists, descending by frequency)
    """
    # Top artists (with genres)
    ta_resp = sp.current_user_top_artists(limit=top_artists_limit, time_range=time_range)
    top_artists = []
    for artist in (ta_resp or {}).get("items", []):
        top_artists.append(
            {
                "id": artist.get("id"),
                "name": artist.get("name"),
                "genres": artist.get("genres", []) or [],
            }
        )

    # Top tracks
    tt_resp = sp.current_user_top_tracks(limit=top_tracks_limit, time_range=time_range)
    top_tracks = []
    for track in (tt_resp or {}).get("items", []):
        artists = track.get("artists", []) or []
        top_tracks.append(
            {
                "id": track.get("id"),
                "name": track.get("name"),
                "artist_ids": _extract_artist_ids(artists),
                "artist_names": _extract_artist_names(artists),
            }
        )

    # Recently played
    rp_resp = sp.current_user_recently_played(limit=recently_played_limit)
    recent_tracks = []
    for item in (rp_resp or {}).get("items", []):
        track = (item or {}).get("track") or {}
        artists = track.get("artists", []) or []
        recent_tracks.append(
            {
                "id": track.get("id"),
                "name": track.get("name"),
                "artist_ids": _extract_artist_ids(artists),
                "artist_names": _extract_artist_names(artists),
                "played_at": item.get("played_at"),
            }
        )

    # Saved tracks (optional; degrade gracefully on 403)
    saved_tracks = []
    try:
        st_resp = sp.current_user_saved_tracks(limit=saved_tracks_limit)
        for item in (st_resp or {}).get("items", []) or []:
            track = (item or {}).get("track") or {}
            artists = track.get("artists", []) or []
            saved_tracks.append(
                {
                    "id": track.get("id"),
                    "name": track.get("name"),
                    "artist_ids": _extract_artist_ids(artists),
                    "artist_names": _extract_artist_names(artists),
                }
            )
    except Exception:
        # Proceed without saved-track info
        saved_tracks = []

    # Known sets
    known_tracks: Set[str] = set()
    for t in top_tracks:
        if t.get("id"):
            known_tracks.add(t["id"])
    for t in recent_tracks:
        if t.get("id"):
            known_tracks.add(t["id"])
    for t in saved_tracks:
        if t.get("id"):
            known_tracks.add(t["id"])

    known_artists: Set[str] = set()
    for a in top_artists:
        if a.get("id"):
            known_artists.add(a["id"])
    for t in top_tracks:
        for aid in t.get("artist_ids", []) or []:
            known_artists.add(aid)
    for t in recent_tracks:
        for aid in t.get("artist_ids", []) or []:
            known_artists.add(aid)
    for t in saved_tracks:
        for aid in t.get("artist_ids", []) or []:
            known_artists.add(aid)

    # Aggregate top genres from top artists
    genre_counter: Counter[str] = Counter()
    for a in top_artists:
        for g in a.get("genres", []) or []:
            if isinstance(g, str) and g:
                genre_counter[g] += 1
    top_artist_genres: List[str] = [g for g, _ in genre_counter.most_common()]

    return {
        "top_artists": top_artists,
        "top_tracks": top_tracks,
        "recent_tracks": recent_tracks,
        "known_artists": known_artists,
        "known_tracks": known_tracks,
        "top_artist_genres": top_artist_genres,
    }


__all__ = ["get_user_profile"]
