# Song of the Day – Full-stack App

A deployable web app that connects to Spotify, lets users select a mood, requests a daily recommendation, and plays it in-page with graceful fallbacks.

## Constraints respected
- No calls to `/v1/recommendations` or `/v1/audio-features`.
- Recommender uses allowed endpoints only (recently-played, top-artists, top-tracks, me/tracks when granted, related-artists, artist top-tracks, search, tracks/{id}).
- OAuth and tokens handled server-side; no secrets in the browser.
- Playback uses Spotify Web Playback SDK when user has Premium; otherwise fallback to preview or embed.

## Monorepo layout
```
/app
  /backend  (FastAPI)
  /frontend (React + Vite)
docker-compose.yml
```

## Environment
Create a `.env` file with:
```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8000/auth/callback
SESSION_SECRET=some_random_string
APP_BASE_URL=http://localhost:5173
```

Spotify app settings:
- Redirect URI: `http://localhost:8000/auth/callback`
- Scopes:
  - user-read-recently-played user-top-read user-library-read
  - user-read-email user-read-private
  - user-modify-playback-state user-read-playback-state streaming

## Local development
```
docker compose up --build
```
- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

## Usage
1. Open the frontend and click "Connect Spotify".
2. Select a mood (optional).
3. Click "Get Song of the Day".
4. Playback will attempt via Web Playback SDK (Premium only). If it fails, a preview (30s) or an embed will appear, and an "Open in Spotify" link is always available.

## API overview
- GET `/auth/login` → start OAuth
- GET `/auth/callback` → exchange code and set session cookie
- GET `/api/me` → { display_name, premium }
- POST `/api/recommend` body `{ mood: 'Happy'|'Sad'|'Energetic'|'Calm'|null }` → track info + rationale
- GET `/api/player/token` → short-lived user token for Web Playback SDK
- POST `/api/player/transfer` → transfer playback to SDK device
- PUT `/api/player/play` → start playback

## Tests
- Add unit tests for auth callback handling, recommend fallback when missing scopes, and playback endpoints using mocked Spotify clients.

## Notes
- If `user-library-read` is not granted, recommender degrades gracefully and still returns a pick.
- The app avoids restricted endpoints explicitly.
- Web Playback SDK requires a Spotify Premium account.
