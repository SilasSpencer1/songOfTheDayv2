from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, Tuple, List

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import math
import aiosqlite

import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials

APP_NAME = "sotd"

# Config from env
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(16))
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173")
ALLOWED_ORIGINS = [APP_BASE_URL]
ADMIN_USER_IDS = set([u for u in (os.getenv("ADMIN_USER_IDS", "").split(",")) if u])

# Scopes per spec
LOGIN_SCOPES = " ".join([
    "user-read-recently-played",
    "user-top-read",
    "user-library-read",
    "user-library-modify",
    "user-read-email",
    "user-read-private",
    "user-modify-playback-state",
    "user-read-playback-state",
    "streaming",
    "playlist-modify-public",
    "playlist-modify-private",
])

# Cookie names: prefer host-only __Host- cookie to avoid parent-domain collisions
SESSION_COOKIE = f"__Host-{APP_NAME}_sid"
LEGACY_SESSION_COOKIE = f"{APP_NAME}_sid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
COOKIE_SECURE = APP_BASE_URL.startswith("https://")
# Use SameSite=None for cross-site (production, https), Lax for local dev
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"

# Database path
DB_PATH_RAW = os.getenv("DATABASE_PATH", "./app/backend/app/data.db")
ANALYTICS_DB_PATH_RAW = os.getenv("ANALYTICS_DB_PATH", "./app/backend/app/analytics.db")


def _resolve_db_path(raw_path: str) -> str:
    # Expand env and user
    path = os.path.expanduser(os.path.expandvars(raw_path))
    dir_path = os.path.dirname(path) or "."
    try:
        os.makedirs(dir_path, exist_ok=True)
        # Touch the file if not exists to verify permissions
        if not os.path.exists(path):
            with open(path, "a"):
                pass
        return path
    except Exception:
        # Fallback to /tmp if not writable
        tmp_path = "/tmp/sotd_data.db"
        tmp_dir = os.path.dirname(tmp_path)
        os.makedirs(tmp_dir, exist_ok=True)
        if not os.path.exists(tmp_path):
            with open(tmp_path, "a"):
                pass
        return tmp_path


DB_PATH = _resolve_db_path(DB_PATH_RAW)
ANALYTICS_DB_PATH = _resolve_db_path(ANALYTICS_DB_PATH_RAW)

app = FastAPI(title="Song of the Day API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Ensure no proxy/CDN caches personalized responses; vary on Cookie
@app.middleware("http")
async def no_cache_for_auth_and_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/auth", "/api")):
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        # Make sure caches/proxies separate by Cookie
        existing_vary = response.headers.get("Vary")
        if existing_vary:
            if "Cookie" not in existing_vary:
                response.headers["Vary"] = existing_vary + ", Cookie"
        else:
            response.headers["Vary"] = "Cookie"
    return response


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                user_id TEXT,
                display_name TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                session_id TEXT NOT NULL,
                track_id TEXT NOT NULL,
                picked_at DATE NOT NULL,
                user_id TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                track_id TEXT NOT NULL,
                mood TEXT,
                score INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS models (
                mood TEXT PRIMARY KEY,
                w0 REAL NOT NULL,
                w1 REAL NOT NULL,
                w2 REAL NOT NULL,
                w3 REAL NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        # Lightweight migrations: ensure columns and indexes exist
        # Add missing columns for sessions
        async with db.execute("PRAGMA table_info(sessions)") as cur:
            cols = [row[1] async for row in cur]
        if "user_id" not in cols:
            await db.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        if "display_name" not in cols:
            await db.execute("ALTER TABLE sessions ADD COLUMN display_name TEXT")

        # Add missing column for history
        async with db.execute("PRAGMA table_info(history)") as cur:
            hcols = [row[1] async for row in cur]
        if "user_id" not in hcols:
            await db.execute("ALTER TABLE history ADD COLUMN user_id TEXT")

        # Create unique indexes to enforce per-user constraints
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_history_user_day ON history(user_id, picked_at)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_history_user_track ON history(user_id, track_id)"
        )

        await db.commit()

    # Initialize analytics mirror DB (non-sensitive)
    async with aiosqlite.connect(ANALYTICS_DB_PATH) as adb:
        await adb.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL
            )
            """
        )
        await adb.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                track_id TEXT NOT NULL,
                picked_at DATE NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        await adb.execute(
            "CREATE INDEX IF NOT EXISTS ix_ah_user_day ON analytics_history(user_id, picked_at)"
        )
        await adb.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_ah_unique ON analytics_history(user_id, track_id, picked_at)"
        )
        await adb.commit()


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()

# Utilities

def make_auth(show_dialog: bool = False) -> SpotifyOAuth:
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REDIRECT_URI):
        raise RuntimeError("Missing Spotify credentials in env")
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=LOGIN_SCOPES,
        cache_path=None,
        open_browser=False,
        show_dialog=show_dialog,
    )


async def save_session(session_id: str, access: str, refresh: str, expires_in: int, *, user_id: Optional[str] = None, display_name: Optional[str] = None) -> None:
    expires_at = int(time.time()) + int(expires_in) - 30
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sessions (session_id, access_token, refresh_token, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET access_token=excluded.access_token,
                                                 refresh_token=excluded.refresh_token,
                                                  expires_at=excluded.expires_at
            """,
            (session_id, access, refresh, expires_at, now),
        )
        # Update user metadata if provided (only set once unless new info provided)
        if user_id is not None or display_name is not None:
            await db.execute(
                "UPDATE sessions SET user_id=COALESCE(?, user_id), display_name=COALESCE(?, display_name) WHERE session_id=?",
                (user_id, display_name, session_id),
            )
        await db.commit()


async def delete_session(session_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await db.commit()


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT session_id, access_token, refresh_token, expires_at, user_id, display_name FROM sessions WHERE session_id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "session_id": row[0],
                "access_token": row[1],
                "refresh_token": row[2],
                "expires_at": row[3],
                "user_id": row[4],
                "display_name": row[5],
            }


async def refresh_if_needed(session: Dict[str, Any]) -> Dict[str, Any]:
    if session["expires_at"] > time.time() + 30:
        return session
    auth = make_auth()
    token_info = auth.refresh_access_token(session["refresh_token"])  # type: ignore
    await save_session(
        session["session_id"],
        token_info["access_token"],
        token_info.get("refresh_token", session["refresh_token"]),
        token_info["expires_in"],
    )
    session.update(
        {
            "access_token": token_info["access_token"],
            "refresh_token": token_info.get("refresh_token", session["refresh_token"]),
            "expires_at": int(time.time()) + int(token_info["expires_in"]) - 30,
        }
    )
    return session


async def require_session(request: Request) -> Dict[str, Any]:
    # Prefer the new host-only cookie; fall back to legacy name if present
    sid = request.cookies.get(SESSION_COOKIE) or request.cookies.get(LEGACY_SESSION_COOKIE)
    if not sid:
        raise HTTPException(status_code=401, detail="Not logged in")
    session = await get_session(sid)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    session = await refresh_if_needed(session)
    return session


async def require_admin(session=Depends(require_session)) -> Dict[str, Any]:
    user_id = session.get("user_id")
    if not user_id or (ADMIN_USER_IDS and user_id not in ADMIN_USER_IDS):
        raise HTTPException(status_code=403, detail="Admin access required")
    return session


# Auth routes
@app.get("/auth/login")
async def auth_login(request: Request) -> Response:
    # If force=1, show Spotify login/consent dialog even if already signed-in
    force = request.query_params.get("force") in {"1", "true", "True"}
    auth = make_auth(show_dialog=bool(force))
    # CSRF state
    state = secrets.token_urlsafe(16)
    url = auth.get_authorize_url(state=state)  # type: ignore
    resp = RedirectResponse(url)
    # Bind state to host-only cookie for verification in callback
    unused = "";
    host = request.url.hostname or ""
    resp.set_cookie(
        key=f"{APP_NAME}_oauth_state",
        value=state,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=300,
        path="/",
    )
    return resp


@app.get("/auth/callback")
async def auth_callback(request: Request) -> Response:
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if error:
        return JSONResponse({"error": error}, status_code=400)
    if not code:
        return JSONResponse({"error": "Missing code"}, status_code=400)
    # Verify OAuth state
    state_q = request.query_params.get("state")
    state_c = request.cookies.get(f"{APP_NAME}_oauth_state")
    if not state_q or not state_c or state_q != state_c:
        return JSONResponse({"error": "Invalid state"}, status_code=400)

    auth = make_auth()
    try:
        token_info = auth.get_access_token(code, as_dict=True)  # type: ignore
    except Exception as e:
        # Surface the OAuth failure instead of 500, to diagnose env/redirect issues
        return JSONResponse({"error": "oauth_token_exchange_failed", "detail": str(e)}, status_code=400)
    if not token_info or not token_info.get("access_token"):
        return JSONResponse({"error": "oauth_token_missing", "detail": str(token_info)}, status_code=400)
    # Fetch Spotify user identity to bind sessions and history per user
    try:
        sp_user = spotipy.Spotify(auth=token_info["access_token"])  # type: ignore
        me = sp_user.me()
    except Exception as e:
        return JSONResponse({"error": "spotify_me_failed", "detail": str(e)}, status_code=400)
    user_id = (me or {}).get("id")
    display_name = (me or {}).get("display_name") or user_id
    if not user_id:
        return JSONResponse({"error": "spotify_me_missing_user"}, status_code=400)

    session_id = secrets.token_urlsafe(24)
    await save_session(
        session_id,
        token_info["access_token"],
        token_info["refresh_token"],
        token_info["expires_in"],
        user_id=user_id,
        display_name=display_name,
    )
    # Mirror to analytics (non-sensitive)
    try:
        now = int(time.time())
        async with aiosqlite.connect(ANALYTICS_DB_PATH) as adb:
            await adb.execute(
                "INSERT INTO analytics_users(user_id, display_name, first_seen, last_seen) VALUES(?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name, last_seen=excluded.last_seen",
                (user_id, display_name, now, now),
            )
            await adb.commit()
    except Exception:
        pass
    resp = RedirectResponse(APP_BASE_URL)
    # Clear state cookie
    resp.set_cookie(
        key=f"{APP_NAME}_oauth_state",
        value="",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=0,
        path="/",
    )
    # Set new host-only session cookie
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    # Proactively expire legacy cookie name if sent by the browser
    resp.set_cookie(
        key=LEGACY_SESSION_COOKIE,
        value="",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=0,
        path="/",
    )
    return resp


@app.post("/auth/logout")
async def auth_logout(request: Request) -> Response:
    sid = request.cookies.get(SESSION_COOKIE) or request.cookies.get(LEGACY_SESSION_COOKIE)
    if sid:
        await delete_session(sid)
    resp = JSONResponse({"ok": True})
    # Expire the cookie(s)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value="",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=0,
        path="/",
    )
    resp.set_cookie(
        key=LEGACY_SESSION_COOKIE,
        value="",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=0,
        path="/",
    )
    resp.set_cookie(
        key=f"{APP_NAME}_oauth_state",
        value="",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=0,
        path="/",
    )
    return resp


# /api/me to show minimal profile info and premium flag
@app.get("/api/me")
async def api_me(session=Depends(require_session)) -> Response:
    sp = spotipy.Spotify(auth=session["access_token"])  # user-auth client
    try:
        # Always use live /me so identity can never be stale
        me = sp.me()
        display_name = me.get("display_name") or me.get("id")
        product = (me.get("product") or "free").lower()
        premium = product == "premium"
        return JSONResponse({"display_name": display_name, "user_id": me.get("id"), "premium": premium})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# Recommendation API
class RecommendBody(BaseModel):
    mood: Optional[str] = None


@app.post("/api/recommend")
async def api_recommend(body: RecommendBody, session=Depends(require_session)) -> Response:
    # Determine "today" in Eastern Time to enforce one-pick-per-day
    est_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    # Identify user (bound at auth time). If missing, fetch now as a fallback.
    user_id = session.get("user_id")
    if not user_id:
        try:
            sp_tmp = spotipy.Spotify(auth=session["access_token"])  # type: ignore
            me_tmp = sp_tmp.me()
            user_id = me_tmp.get("id")
            display_name = me_tmp.get("display_name") or user_id
            # Persist into session for future requests
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE sessions SET user_id = ?, display_name = ? WHERE session_id = ?",
                    (user_id, display_name, session["session_id"]),
                )
                await db.commit()
        except Exception:
            user_id = None

    # If we cannot determine user, do not proceed
    if not user_id:
        return JSONResponse({"error": "Unable to identify Spotify user"}, status_code=401)

    # Backfill any legacy history rows tied to this session without user_id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE history SET user_id = ? WHERE session_id = ? AND (user_id IS NULL OR user_id = '')",
            (user_id, session["session_id"]),
        )
        await db.commit()

    # If a pick already exists for today for this user, return it
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT track_id FROM history WHERE user_id = ? AND picked_at = ?",
            (user_id, est_today),
        ) as cur:
            row = await cur.fetchone()
    if row and row[0]:
        track_id = row[0]
        from sotd.auth import get_catalog_client  # type: ignore
        cat = get_catalog_client()
        try:
            track = cat.track(track_id)
        except Exception as e:
            return JSONResponse({"message": "Could not fetch today's pick", "error": str(e)}, status_code=400)

        images = ((track.get("album") or {}).get("images") or [])
        album_image_url = images[0].get("url") if images else None
        payload = {
            "track_id": track_id,
            "track_uri": track.get("uri"),
            "name": track.get("name"),
            "artist": ", ".join(a.get("name") for a in (track.get("artists") or [])),
            "album": (track.get("album") or {}).get("name"),
            "album_image_url": album_image_url,
            "spotify_url": f"https://open.spotify.com/track/{track_id}",
            "preview_url": track.get("preview_url"),
            "why": {"note": "Today's pick is already set. New pick after 12:00am ET."},
            "already_picked": True,
        }
        return JSONResponse(payload)
    # Build user-auth client for profile endpoints
    sp_user = spotipy.Spotify(auth=session["access_token"])  # user token

    # Import and call existing recommender
    from sotd.recommend import song_of_the_day  # type: ignore
    from sotd.profile import get_user_profile  # type: ignore
    from sotd.candidates import generate_candidates, filter_candidates_by_mood  # type: ignore
    from sotd.auth import get_catalog_client  # type: ignore

    profile = get_user_profile(sp_user)
    candidates = generate_candidates(sp_user, profile)
    # Exclude any tracks previously recommended to this user
    prior_recs: List[str] = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT track_id FROM history WHERE user_id = ?", (user_id,)) as cur:
            async for r in cur:
                prior_recs.append(r[0])
    if prior_recs:
        prior_set = set(prior_recs)
        candidates = [tid for tid in candidates if tid not in prior_set]
    if not candidates:
        return JSONResponse({"message": "No candidate found today"}, status_code=200)
    # Model-aware ranking
    cat = get_catalog_client()  # client-credentials
    desired_mood = (body.mood or "").lower().strip() or None

    # Import mood config used for features
    from sotd.mood import mood_genres, POPULARITY_TARGET, RECENCY_BIAS_YEARS  # type: ignore

    desired_genres = mood_genres(desired_mood) if desired_mood else set()
    pop_target = POPULARITY_TARGET.get(desired_mood, 0.5)
    recency_years = RECENCY_BIAS_YEARS.get(desired_mood, 10)

    # Load (or initialize) model weights for this mood
    async def get_model(mood: str) -> List[float]:
        m = mood or "none"
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT w0, w1, w2, w3 FROM models WHERE mood=?", (m,)) as cur:
                row = await cur.fetchone()
            if row:
                return [row[0], row[1], row[2], row[3]]
            # Initialize with heuristic weights
            w = [0.0, 0.6, 0.25, 0.15]
            now = int(time.time())
            await db.execute(
                "INSERT OR REPLACE INTO models (mood, w0, w1, w2, w3, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (m, w[0], w[1], w[2], w[3], now),
            )
            await db.commit()
            return w

    def sigmoid(x: float) -> float:
        try:
            if x < -60:
                return 0.0
            if x > 60:
                return 1.0
            return 1.0 / (1.0 + math.exp(-x))
        except Exception:
            return 0.5

    # Batch fetch track objects and artist genres for features
    def _batched(lst: List[str], size: int) -> List[List[str]]:
        return [lst[i:i+size] for i in range(0, len(lst), size)]

    track_objects: Dict[str, Dict[str, Any]] = {}
    for batch in _batched(candidates[:50], 50):
        try:
            resp = cat.tracks(batch) or {}
            for t in resp.get("tracks", []) or []:
                if t and t.get("id"):
                    track_objects[t["id"]] = t
        except Exception:
            continue

    # Collect artist IDs
    artist_ids: List[str] = []
    for t in track_objects.values():
        for a in (t.get("artists") or []):
            aid = a.get("id")
            if aid:
                artist_ids.append(aid)
    # Deduplicate
    seen: Dict[str, bool] = {}
    unique_artist_ids: List[str] = []
    for aid in artist_ids:
        if aid not in seen:
            seen[aid] = True
            unique_artist_ids.append(aid)

    artist_genres_map: Dict[str, List[str]] = {}
    for batch in _batched(unique_artist_ids, 50):
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
            return int((date_str or "").split("-")[0])
        except Exception:
            return None

    def feature_tuple(t: Dict[str, Any]) -> List[float]:
        # genre overlap (union-based Jaccard with mood genres)
        gset: set[str] = set()
        for a in (t.get("artists") or []):
            aid = a.get("id")
            if aid and artist_genres_map.get(aid):
                gset.update(artist_genres_map[aid])
        if desired_genres:
            inter = len(gset.intersection(desired_genres))
            union = max(1, len(gset.union(desired_genres)))
            genre_fit = inter / union
        else:
            genre_fit = 0.0
        popularity = float(t.get("popularity") or 0.0) / 100.0
        pop_fit = 1.0 - abs(popularity - pop_target)
        # recency
        year = parse_year(((t.get("album") or {}).get("release_date")))
        if year is not None:
            age_years = max(0, datetime.utcnow().year - year)
            recency_fit = max(0.0, 1.0 - (age_years / max(1, recency_years)))
        else:
            recency_fit = 0.5
        return [1.0, genre_fit, pop_fit, recency_fit]

    # Compute model scores
    w = await get_model(desired_mood or "none")
    scored: List[Tuple[str, float]] = []
    for tid, tobj in track_objects.items():
        x = feature_tuple(tobj)
        z = w[0]*x[0] + w[1]*x[1] + w[2]*x[2] + w[3]*x[3]
        p = sigmoid(z)
        scored.append((tid, p))

    if not scored:
        # Fallback to heuristic ranking when catalog fetch fails
        filtered = filter_candidates_by_mood(candidates, mood=body.mood) if body.mood else candidates
        if not filtered:
            return JSONResponse({"message": "No candidate found today"}, status_code=200)
        track_id = filtered[0]
        track = cat.track(track_id)
    else:
        scored.sort(key=lambda t: t[1], reverse=True)
        track_id = scored[0][0]
        track = track_objects.get(track_id) or cat.track(track_id)

    # Build rationale (heuristic example)
    seeds = []
    if profile.get("top_artists"):
        seeds.append(profile["top_artists"][0].get("name"))
    if profile.get("top_artist_genres"):
        seeds.append(profile["top_artist_genres"][0])

    why = {
        "seeds": [s for s in seeds if s],
        "mood_fit": {
            "mood": body.mood,
            "valence": None,
            "energy": None,
            "source": "model+heuristic",
        },
        "novelty": {
            "new_artist": (track.get("artists") or [{}])[0].get("id") not in profile.get("known_artists", set()),
            "known_overlap": 0,
        },
    }

    images = ((track.get("album") or {}).get("images") or [])
    album_image_url = images[0].get("url") if images else None

    payload = {
        "track_id": track_id,
        "track_uri": track.get("uri"),
        "name": track.get("name"),
        "artist": ", ".join(a.get("name") for a in (track.get("artists") or [])),
        "album": (track.get("album") or {}).get("name"),
        "album_image_url": album_image_url,
        "spotify_url": f"https://open.spotify.com/track/{track_id}",
        "preview_url": track.get("preview_url"),
        "why": why,
    }

    # Persist daily history (per-user, Eastern Time day key), and uniqueness across all time
    async with aiosqlite.connect(DB_PATH) as db:
        # First, insert the recommendation record; unique index prevents duplicates
        await db.execute(
            "INSERT OR IGNORE INTO history (session_id, track_id, picked_at, user_id) VALUES (?, ?, ?, ?)",
            (session["session_id"], track_id, est_today, user_id),
        )
        await db.commit()

    # Mirror to analytics DB (no tokens)
    try:
        now = int(time.time())
        async with aiosqlite.connect(ANALYTICS_DB_PATH) as adb:
            await adb.execute(
                "INSERT OR IGNORE INTO analytics_history(user_id, track_id, picked_at, created_at) VALUES(?, ?, ?, ?)",
                (user_id, track_id, est_today, now),
            )
            await adb.commit()
    except Exception:
        pass

    return JSONResponse(payload)


# Admin stats API (protected by ADMIN_USER_IDS)
@app.get("/api/admin/stats")
async def api_admin_stats(session=Depends(require_admin)) -> Response:
    # Compute date window for last 7 days in ET
    est = ZoneInfo("America/New_York")
    today = datetime.now(est).date()
    start_7 = (today - timedelta(days=6)).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        # Totals
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE user_id IS NOT NULL") as cur:
            row = await cur.fetchone()
            total_users = row[0] or 0
        async with db.execute("SELECT COUNT(*) FROM history WHERE user_id IS NOT NULL") as cur:
            row = await cur.fetchone()
            total_sotds = row[0] or 0

        # Last 7 days
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM history WHERE user_id IS NOT NULL AND picked_at >= ?", (start_7,)) as cur:
            row = await cur.fetchone()
            users_last_7_days = row[0] or 0
        async with db.execute("SELECT COUNT(*) FROM history WHERE user_id IS NOT NULL AND picked_at >= ?", (start_7,)) as cur:
            row = await cur.fetchone()
            sotds_last_7_days = row[0] or 0

        # Top tracks
        top_tracks: List[Tuple[str, int]] = []
        async with db.execute("SELECT track_id, COUNT(*) as c FROM history WHERE user_id IS NOT NULL GROUP BY track_id ORDER BY c DESC LIMIT 10") as cur:
            async for row in cur:
                top_tracks.append((row[0], row[1]))

        # Users (id -> display name)
        user_display: Dict[str, str] = {}
        async with db.execute("SELECT user_id, MAX(display_name) FROM sessions WHERE user_id IS NOT NULL GROUP BY user_id") as cur:
            async for row in cur:
                if row[0]:
                    user_display[row[0]] = row[1] or row[0]

        # Top users by SOTDs
        top_users: List[Tuple[str, int]] = []
        async with db.execute("SELECT user_id, COUNT(*) as c FROM history WHERE user_id IS NOT NULL GROUP BY user_id ORDER BY c DESC LIMIT 10") as cur:
            async for row in cur:
                uid = row[0]
                cnt = row[1]
                if uid:
                    top_users.append((user_display.get(uid, uid), cnt))

    # Optionally enrich top_tracks with names
    enriched_tracks: List[Dict[str, Any]] = []
    try:
        from sotd.auth import get_catalog_client  # type: ignore
        cat = get_catalog_client()
        ids = [tid for tid, _ in top_tracks]
        if ids:
            resp = cat.tracks(ids) or {}
            by_id = {t.get("id"): t for t in (resp.get("tracks") or []) if t}
            for tid, cnt in top_tracks:
                t = by_id.get(tid) or {}
                enriched_tracks.append({
                    "track_id": tid,
                    "name": t.get("name"),
                    "artist": ", ".join(a.get("name") for a in (t.get("artists") or [])),
                    "count": cnt,
                })
    except Exception:
        for tid, cnt in top_tracks:
            enriched_tracks.append({"track_id": tid, "name": None, "artist": None, "count": cnt})

    return JSONResponse({
        "total_users": total_users,
        "total_sotds": total_sotds,
        "users_last_7_days": users_last_7_days,
        "sotds_last_7_days": sotds_last_7_days,
        "top_tracks": enriched_tracks,
        "top_users": [{"display_name": name, "count": cnt} for name, cnt in top_users],
        "window_start": start_7,
        "today": today.isoformat(),
    })


# Playback helper APIs
@app.get("/api/player/token")
async def api_player_token(session=Depends(require_session)) -> Response:
    # Return short-lived user access token for Web Playback SDK
    return JSONResponse({"access_token": session["access_token"]})


class TransferBody(BaseModel):
    device_id: str


@app.post("/api/player/transfer")
async def api_player_transfer(body: TransferBody, session=Depends(require_session)) -> Response:
    sp = spotipy.Spotify(auth=session["access_token"])  # user-auth client
    try:
        sp.transfer_playback(device_id=body.device_id, force_play=True)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


class PlayBody(BaseModel):
    device_id: Optional[str] = None
    uris: Optional[list[str]] = None


@app.put("/api/player/play")
async def api_player_play(body: PlayBody, session=Depends(require_session)) -> Response:
    sp = spotipy.Spotify(auth=session["access_token"])  # user-auth client
    try:
        sp.start_playback(device_id=body.device_id, uris=body.uris)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# Library helpers
class SaveLikeBody(BaseModel):
    track_id: str


@app.post("/api/like")
async def api_like(body: SaveLikeBody, session=Depends(require_session)) -> Response:
    try:
        sp = spotipy.Spotify(auth=session["access_token"])  # user-auth client
        sp.current_user_saved_tracks_add([body.track_id])
        return JSONResponse({"ok": True})
    except Exception as e:
        # surface 403 when scope missing
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


class AddToPlaylistBody(BaseModel):
    playlist_id: str
    track_uri: str


@app.post("/api/playlist/add")
async def api_playlist_add(body: AddToPlaylistBody, session=Depends(require_session)) -> Response:
    try:
        sp = spotipy.Spotify(auth=session["access_token"])  # user-auth client
        sp.playlist_add_items(body.playlist_id, [body.track_uri])
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# Feedback API (rubric score: -1, 0, +1)
class FeedbackBody(BaseModel):
    track_id: str
    mood: Optional[str] = None
    score: int  # -1 disliked for mood, 0 neutral/skip, +1 good fit


@app.post("/api/feedback")
async def api_feedback(body: FeedbackBody, session=Depends(require_session)) -> Response:
    s = max(-1, min(1, int(body.score)))
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO feedback (session_id, track_id, mood, score, created_at) VALUES (?, ?, ?, ?, ?)",
            (session["session_id"], body.track_id, (body.mood or "none").lower(), s, now),
        )
        await db.commit()

    # Online update of logistic weights via simple gradient step
    # Use the features from the same logic in /api/recommend
    try:
        from sotd.auth import get_catalog_client  # type: ignore
        cat = get_catalog_client()
        t = cat.track(body.track_id)
        desired_mood = (body.mood or "none").lower()
        from sotd.mood import mood_genres, POPULARITY_TARGET, RECENCY_BIAS_YEARS  # type: ignore
        desired_genres = mood_genres(desired_mood)
        pop_target = POPULARITY_TARGET.get(desired_mood, 0.5)
        recency_years = RECENCY_BIAS_YEARS.get(desired_mood, 10)

        # Fetch artist genres
        artist_ids: List[str] = [a.get("id") for a in (t.get("artists") or []) if a.get("id")]
        artist_genres_map: Dict[str, List[str]] = {}
        if artist_ids:
            resp = cat.artists(artist_ids) or {}
            for a in resp.get("artists", []) or []:
                if a and a.get("id"):
                    artist_genres_map[a["id"]] = a.get("genres", []) or []

        def parse_year(date_str: Optional[str]) -> Optional[int]:
            if not date_str:
                return None
            try:
                return int((date_str or "").split("-")[0])
            except Exception:
                return None

        # Build features
        gset: set[str] = set()
        for a in (t.get("artists") or []):
            aid = a.get("id")
            if aid and artist_genres_map.get(aid):
                gset.update(artist_genres_map[aid])
        if desired_genres:
            inter = len(gset.intersection(desired_genres))
            union = max(1, len(gset.union(desired_genres)))
            genre_fit = inter / union
        else:
            genre_fit = 0.0
        popularity = float(t.get("popularity") or 0.0) / 100.0
        pop_fit = 1.0 - abs(popularity - pop_target)
        year = parse_year(((t.get("album") or {}).get("release_date")))
        if year is not None:
            age_years = max(0, datetime.utcnow().year - year)
            recency_fit = max(0.0, 1.0 - (age_years / max(1, recency_years)))
        else:
            recency_fit = 0.5
        x = [1.0, genre_fit, pop_fit, recency_fit]

        # Load current weights
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT w0, w1, w2, w3 FROM models WHERE mood=?", (desired_mood,)) as cur:
                row = await cur.fetchone()
            if row:
                w = [row[0], row[1], row[2], row[3]]
            else:
                w = [0.0, 0.6, 0.25, 0.15]
            # Prediction
            def sigmoid(z: float) -> float:
                try:
                    if z < -60:
                        return 0.0
                    if z > 60:
                        return 1.0
                    return 1.0 / (1.0 + math.exp(-z))
                except Exception:
                    return 0.5
            z = w[0]*x[0] + w[1]*x[1] + w[2]*x[2] + w[3]*x[3]
            p = sigmoid(z)
            # Map rubric score to target y in {0,1}
            y = 1.0 if s > 0 else 0.0
            # One-step gradient for logistic loss
            lr = 0.2
            grad = [(p - y) * xi for xi in x]
            w = [w[i] - lr * grad[i] for i in range(4)]
            now2 = int(time.time())
            await db.execute(
                "INSERT OR REPLACE INTO models (mood, w0, w1, w2, w3, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (desired_mood, w[0], w[1], w[2], w[3], now2),
            )
            await db.commit()
    except Exception:
        pass

    return JSONResponse({"ok": True})
