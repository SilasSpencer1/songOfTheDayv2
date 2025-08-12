from __future__ import annotations

from typing import Any, Dict, List, Set, Optional, Iterable, Tuple
import random
import os
import logging
from datetime import datetime

from sotd.auth import get_catalog_client
from sotd.mood import mood_genres, POPULARITY_TARGET, RECENCY_BIAS_YEARS


def _pick_n(sequence: List[Any], n: int) -> List[Any]:
    if n <= 0:
        return []
    if len(sequence) <= n:
        return list(sequence)
    return random.sample(sequence, n)


def _batched(seq: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def generate_candidates(
    sp: Any,
    profile: Dict[str, Any],
    *,
    max_related_artists: int = 10,
    enable_related: Optional[bool] = None,
) -> List[str]:
    """
    Generate a list of candidate track IDs using related artists (if enabled) and genre searches.

    Uses a separate catalog client (client credentials) for public catalog endpoints to avoid 401/404 issues.
    """
    known_artists: Set[str] = set(profile.get("known_artists", set()))
    known_tracks: Set[str] = set(profile.get("known_tracks", set()))

    # Catalog client for public endpoints
    cat = get_catalog_client()

    # Decide whether to use related artists
    if enable_related is None:
        enable_related = os.getenv("SOTD_ENABLE_RELATED", "0") in {"1", "true", "True"}

    candidate_track_ids: List[str] = []
    collected_artist_ids: List[str] = []

    if enable_related:
        # Suppress Spotipy error logs to avoid noisy 404 prints
        spotipy_logger = logging.getLogger("spotipy.client")
        prev_level = spotipy_logger.level
        try:
            spotipy_logger.setLevel(logging.WARNING)

            # Collect related artist IDs not already known to the user
            for artist in profile.get("top_artists", []):
                if len(collected_artist_ids) >= max_related_artists:
                    break
                artist_id = artist.get("id")
                if not artist_id:
                    continue
                try:
                    rel = cat.artist_related_artists(artist_id)
                except Exception:
                    # Skip artists with failing related-artist calls
                    continue
                for a in (rel or {}).get("artists", []):
                    ra_id = a.get("id")
                    if not ra_id or ra_id in known_artists:
                        continue
                    collected_artist_ids.append(ra_id)
                    if len(collected_artist_ids) >= max_related_artists:
                        break
        finally:
            spotipy_logger.setLevel(prev_level)

    # Fallback: if related disabled or insufficient, search for artists by top genres
    if len(collected_artist_ids) < max_related_artists:
        genres: List[str] = list(profile.get("top_artist_genres", []))
        # Search across up to top 5 genres, grab a few artists per genre
        for genre in genres[:5]:
            try:
                # Use type=artist search to approximate "related artists" via shared genres
                search_resp = cat.search(q=f'genre:"{genre}"', type="artist", limit=5)
                for a in (search_resp or {}).get("artists", {}).get("items", []) or []:
                    aid = a.get("id")
                    if not aid or aid in known_artists:
                        continue
                    collected_artist_ids.append(aid)
                    if len(collected_artist_ids) >= max_related_artists:
                        break
            except Exception:
                continue
            if len(collected_artist_ids) >= max_related_artists:
                break

    # Deduplicate artist IDs while preserving order
    seen_ra: Set[str] = set()
    dedup_artists: List[str] = []
    for ra in collected_artist_ids:
        if ra not in seen_ra:
            seen_ra.add(ra)
            dedup_artists.append(ra)

    # From each collected artist, get their top track (US as market default)
    for ra_id in dedup_artists:
        try:
            top_resp = cat.artist_top_tracks(ra_id, country="US")
            tracks = (top_resp or {}).get("tracks", [])
            if not tracks:
                continue
            top_track_id = tracks[0].get("id")
            # Ensure the track's primary artist isn't already known
            primary_artist_id = (tracks[0].get("artists") or [{}])[0].get("id")
            if (
                top_track_id
                and top_track_id not in known_tracks
                and primary_artist_id not in known_artists
            ):
                candidate_track_ids.append(top_track_id)
        except Exception:
            continue

    # Add genre search candidates (up to 2 genres)
    genres_for_tracks: List[str] = list(profile.get("top_artist_genres", []))
    for genre in _pick_n(genres_for_tracks[:5], 2):  # sample from up to top 5 genres
        try:
            query = f'genre:"{genre}"'
            search_resp = cat.search(q=query, type="track", limit=5)
            for item in (search_resp or {}).get("tracks", {}).get("items", []) or []:
                tid = item.get("id")
                primary_artist_id = (item.get("artists") or [{}])[0].get("id")
                if (
                    tid
                    and tid not in known_tracks
                    and primary_artist_id not in known_artists
                ):
                    candidate_track_ids.append(tid)
                    break  # take 1 per genre
        except Exception:
            continue

    # De-duplicate and filter out any known tracks just in case
    unique: List[str] = []
    seen: Set[str] = set()
    for tid in candidate_track_ids:
        if tid and tid not in seen and tid not in known_tracks:
            seen.add(tid)
            unique.append(tid)

    return unique


def filter_candidates_by_mood(
    candidate_track_ids: List[str],
    *,
    mood: Optional[str] = None,
    top_k: Optional[int] = None,
) -> List[str]:
    """
    Rank/filter candidate track IDs by mood using genre overlap, popularity, and recency.

    This function DOES NOT call audio-features (per constraints). It uses:
      - Track popularity (0-100) vs a mood-specific target
      - Artist genres overlap with mood genres
      - Album release year recency vs mood-specific window

    Returns the filtered and ranked list of track IDs.
    """
    if not mood or not candidate_track_ids:
        return candidate_track_ids

    mood_lower = mood.lower()
    desired_genres: Set[str] = mood_genres(mood_lower)
    pop_target = POPULARITY_TARGET.get(mood_lower, 0.5)
    recency_years = RECENCY_BIAS_YEARS.get(mood_lower, 10)

    cat = get_catalog_client()

    # Fetch track objects (popularity + album date + artists)
    track_objects: Dict[str, Dict[str, Any]] = {}
    for batch in _batched(candidate_track_ids, 50):
        try:
            resp = cat.tracks(batch) or {}
            for t in resp.get("tracks", []) or []:
                if t and t.get("id"):
                    track_objects[t["id"]] = t
        except Exception:
            continue

    # Gather artist genres
    artist_ids: List[str] = []
    for t in track_objects.values():
        for a in (t.get("artists") or []):
            aid = a.get("id")
            if aid:
                artist_ids.append(aid)
    artist_ids = list(dict.fromkeys(artist_ids))  # dedupe preserve order

    artist_genres_map: Dict[str, List[str]] = {}
    for batch in _batched(artist_ids, 50):
        try:
            resp = cat.artists(batch) or {}
            for a in resp.get("artists", []) or []:
                if a and a.get("id"):
                    artist_genres_map[a["id"]] = a.get("genres", []) or []
        except Exception:
            continue

    def parse_year(date_str: Optional[str]) -> Optional[int]:
        if not date_str:
            return None
        try:
            # date may be YYYY-MM-DD or YYYY
            year = int(date_str.split("-")[0])
            return year
        except Exception:
            return None

    def norm(x: float) -> float:
        if x < 0:
            return 0.0
        if x > 1:
            return 1.0
        return x

    scored: List[Tuple[str, float]] = []
    current_year = datetime.utcnow().year

    for tid, t in track_objects.items():
        # Genres from all artists on the track
        gset: Set[str] = set()
        for a in (t.get("artists") or []):
            aid = a.get("id")
            if aid and artist_genres_map.get(aid):
                gset.update(artist_genres_map[aid])

        # Genre overlap score
        if desired_genres:
            inter = len(gset.intersection(desired_genres))
            union = len(gset.union(desired_genres)) or 1
            genre_score = inter / union
        else:
            genre_score = 0.0

        # Popularity proximity score
        pop = float(t.get("popularity") or 0.0) / 100.0
        pop_score = 1.0 - abs(pop - pop_target)
        pop_score = norm(pop_score)

        # Recency score
        rdate = ((t.get("album") or {}).get("release_date"))
        year = parse_year(rdate)
        if year is not None:
            age_years = max(0, current_year - year)
            recency_score = max(0.0, 1.0 - (age_years / max(1, recency_years)))
        else:
            recency_score = 0.5

        # Weighted score
        score = 0.6 * genre_score + 0.25 * pop_score + 0.15 * recency_score
        scored.append((tid, score))

    # If no tracks had metadata fetched, return original list
    if not scored:
        return candidate_track_ids

    # Sort by score desc, stable by original order as tiebreaker
    order_index = {tid: i for i, tid in enumerate(candidate_track_ids)}
    scored.sort(key=lambda x: (x[1], -order_index.get(x[0], 0)), reverse=True)

    ranked = [tid for tid, _ in scored]

    # Optionally filter to those with any genre overlap; if none, just return ranked
    with_overlap = [tid for tid, s in scored if s > 0]
    result = with_overlap or ranked

    if top_k is not None and top_k > 0:
        return result[:top_k]
    return result


__all__ = ["generate_candidates", "filter_candidates_by_mood"]
