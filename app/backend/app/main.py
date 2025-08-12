from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, Tuple

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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

# Scopes per spec
LOGIN_SCOPES = " ".join([
    "user-read-recently-played",
    "user-top-read",
    "user-library-read",
    "user-read-email",
    "user-read-private",
    "user-modify-playback-state",
    "user-read-playback-state",
    "streaming",
])

# Cookie names
SESSION_COOKIE = f"{APP_NAME}_sid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# Database path
DB_PATH = os.getenv("DATABASE_PATH", "./app/backend/app/data.db")


app = FastAPI(title="Song of the Day API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                session_id TEXT NOT NULL,
                track_id TEXT NOT NULL,
                picked_at DATE NOT NULL,
                PRIMARY KEY (session_id, picked_at)
            )
            """
        )
        await db.commit()


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()


# Utilities

def make_auth() -> SpotifyOAuth:
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REDIRECT_URI):
        raise RuntimeError("Missing Spotify credentials in env")
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=LOGIN_SCOPES,
        cache_path=None,
        open_browser=False,
        show_dialog=False,
    )


async def save_session(session_id: str, access: str, refresh: str, expires_in: int) -> None:
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
        await db.commit()


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT session_id, access_token, refresh_token, expires_at FROM sessions WHERE session_id = ?",
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
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        raise HTTPException(status_code=401, detail="Not logged in")
    session = await get_session(sid)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    session = await refresh_if_needed(session)
    return session


# Auth routes
@app.get("/auth/login")
async def auth_login() -> Response:
    auth = make_auth()
    url = auth.get_authorize_url()  # type: ignore
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(request: Request) -> Response:
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if error:
        return JSONResponse({"error": error}, status_code=400)
    if not code:
        return JSONResponse({"error": "Missing code"}, status_code=400)

    auth = make_auth()
    token_info = auth.get_access_token(code, as_dict=True)  # type: ignore
    session_id = secrets.token_urlsafe(24)
    await save_session(
        session_id,
        token_info["access_token"],
        token_info["refresh_token"],
        token_info["expires_in"],
    )
    resp = RedirectResponse(APP_BASE_URL)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    return resp


# /api/me to show minimal profile info and premium flag
@app.get("/api/me")
async def api_me(session=Depends(require_session)) -> Response:
    sp = spotipy.Spotify(auth=session["access_token"])  # user-auth client
    try:
        me = sp.me()
        display_name = me.get("display_name") or me.get("id")
        product = (me.get("product") or "free").lower()
        premium = product == "premium"
        return JSONResponse({"display_name": display_name, "premium": premium})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# Recommendation API
class RecommendBody(BaseModel):
    mood: Optional[str] = None


@app.post("/api/recommend")
async def api_recommend(body: RecommendBody, session=Depends(require_session)) -> Response:
    # Build user-auth client for profile endpoints
    sp_user = spotipy.Spotify(auth=session["access_token"])  # user token

    # Import and call existing recommender
    from sotd.recommend import song_of_the_day  # type: ignore
    from sotd.profile import get_user_profile  # type: ignore
    from sotd.candidates import generate_candidates, filter_candidates_by_mood  # type: ignore
    from sotd.auth import get_catalog_client  # type: ignore

    profile = get_user_profile(sp_user)
    candidates = generate_candidates(sp_user, profile)
    filtered = filter_candidates_by_mood(candidates, mood=body.mood) if body.mood else candidates

    if not filtered:
        return JSONResponse({"message": "No candidate found today"}, status_code=200)

    track_id = filtered[0]
    cat = get_catalog_client()  # client-credentials
    track = cat.track(track_id)

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
            "source": "heuristic",
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

    # Persist daily history
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO history (session_id, track_id, picked_at) VALUES (?, ?, ?)",
            (session["session_id"], track_id, date.today().isoformat()),
        )
        await db.commit()

    return JSONResponse(payload)


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
