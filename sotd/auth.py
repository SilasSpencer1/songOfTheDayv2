import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    # dotenv is optional; ignore if unavailable
    pass

import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials


SOTD_SCOPES = " ".join([
    "user-top-read",
    "user-read-recently-played",
    "user-library-read",
])


def _resolve_cache_path() -> str:
    """Return a stable token cache path under the user's config directory."""
    config_home = os.getenv("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else (Path.home() / ".config")
    token_dir = base / "sotd"
    token_dir.mkdir(parents=True, exist_ok=True)
    return str(token_dir / "token_cache.json")


def get_spotify_client(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    scopes: Optional[str] = None,
) -> spotipy.Spotify:
    """
    Return an authenticated Spotipy client using Authorization Code flow with token caching.

    If no arguments are provided, credentials are read from environment variables:
      - SPOTIFY_CLIENT_ID
      - SPOTIFY_CLIENT_SECRET
      - SPOTIFY_REDIRECT_URI

    The first run will open a browser for user consent and cache the token to avoid re-login.
    """
    resolved_client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
    resolved_client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")
    resolved_redirect_uri = redirect_uri or os.getenv("SPOTIFY_REDIRECT_URI")
    resolved_scopes = scopes or SOTD_SCOPES

    missing = [
        name for name, val in (
            ("SPOTIFY_CLIENT_ID", resolved_client_id),
            ("SPOTIFY_CLIENT_SECRET", resolved_client_secret),
            ("SPOTIFY_REDIRECT_URI", resolved_redirect_uri),
        ) if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing required Spotify credentials: {', '.join(missing)}. "
            "Set environment variables or pass them as arguments."
        )

    auth_manager = SpotifyOAuth(
        client_id=resolved_client_id,
        client_secret=resolved_client_secret,
        redirect_uri=resolved_redirect_uri,
        scope=resolved_scopes,
        cache_path=_resolve_cache_path(),
        open_browser=True,
        show_dialog=False,
    )

    # Spotipy will retrieve/refresh tokens automatically via the auth_manager.
    return spotipy.Spotify(auth_manager=auth_manager)


def get_catalog_client(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> spotipy.Spotify:
    """
    Return a Spotipy client authenticated via Client Credentials for public catalog endpoints
    (e.g., artists, related artists, search, tracks). Uses SPOTIFY_CLIENT_ID/SECRET if not provided.
    """
    resolved_client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
    resolved_client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")

    missing = [
        name for name, val in (
            ("SPOTIFY_CLIENT_ID", resolved_client_id),
            ("SPOTIFY_CLIENT_SECRET", resolved_client_secret),
        ) if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing required Spotify credentials for catalog client: {', '.join(missing)}."
        )

    cc = SpotifyClientCredentials(client_id=resolved_client_id, client_secret=resolved_client_secret)
    return spotipy.Spotify(auth_manager=cc)


__all__ = ["get_spotify_client", "get_catalog_client", "SOTD_SCOPES"]
