import React, { useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

type Mood = 'Happy' | 'Sad' | 'Energetic' | 'Calm' | null

type Me = { display_name: string; premium: boolean }

type RecommendPayload = {
  track_id: string
  track_uri: string
  name: string
  artist: string
  album: string
  album_image_url?: string | null
  spotify_url: string
  preview_url?: string | null
  why?: any
}

export function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [mood, setMood] = useState<Mood>(null)
  const [rec, setRec] = useState<RecommendPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ;(async () => {
      try {
        const res = await axios.get(`${API_BASE}/api/me`, { withCredentials: true })
        setMe(res.data)
      } catch (e: any) {
        setMe(null)
      }
    })()
  }, [])

  const onLogin = () => {
    window.location.href = `${API_BASE}/auth/login`
  }

  const onRecommend = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.post(
        `${API_BASE}/api/recommend`,
        { mood },
        { withCredentials: true }
      )
      setRec(res.data)
    } catch (e: any) {
      setError(e?.response?.data?.error || e.message)
      setRec(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: 16, fontFamily: 'system-ui, sans-serif' }}>
      <h1>Song of the Day</h1>
      {!me ? (
        <LoginGate onLogin={onLogin} />
      ) : (
        <div>
          <p>Welcome, {me.display_name}</p>
          <MoodSelector mood={mood} onChange={setMood} />
          <RecommendCard onRecommend={onRecommend} loading={loading} error={error} rec={rec} />
          <Player rec={rec} premium={me.premium} />
        </div>
      )}
    </div>
  )
}

function LoginGate({ onLogin }: { onLogin: () => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <p>Connect your Spotify account to get a daily recommendation.</p>
      <button onClick={onLogin} style={{ padding: '8px 12px' }}>Connect Spotify</button>
    </div>
  )
}

function MoodSelector({ mood, onChange }: { mood: Mood; onChange: (m: Mood) => void }) {
  const moods: Mood[] = [null, 'Happy', 'Sad', 'Energetic', 'Calm']
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0' }}>
      {moods.map((m) => (
        <button
          key={String(m)}
          onClick={() => onChange(m)}
          style={{
            padding: '6px 10px',
            borderRadius: 16,
            border: '1px solid #ccc',
            background: m === mood ? '#111' : '#fff',
            color: m === mood ? '#fff' : '#111',
          }}
        >
          {m === null ? 'None' : m}
        </button>
      ))}
    </div>
  )
}

function RecommendCard({
  onRecommend,
  loading,
  error,
  rec,
}: {
  onRecommend: () => void
  loading: boolean
  error: string | null
  rec: RecommendPayload | null
}) {
  return (
    <div style={{ border: '1px solid #ddd', padding: 12, borderRadius: 8 }}>
      <button onClick={onRecommend} disabled={loading} style={{ padding: '8px 12px' }}>
        {loading ? 'Loading…' : 'Get Song of the Day'}
      </button>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {rec && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', gap: 12 }}>
            {rec.album_image_url && (
              <img src={rec.album_image_url} width={120} height={120} style={{ objectFit: 'cover', borderRadius: 8 }} />
            )}
            <div>
              <h3 style={{ margin: '4px 0' }}>{rec.name}</h3>
              <p style={{ margin: 0 }}>{rec.artist}</p>
              <a href={rec.spotify_url} target="_blank" rel="noreferrer">Open in Spotify</a>
            </div>
          </div>
          {rec.why && (
            <div style={{ marginTop: 8, fontSize: 14 }}>
              <strong>Why this pick</strong>
              <div>Seeds: {(rec.why.seeds || []).join(', ')}</div>
              {rec.why.mood_fit && (
                <div>Mood: {rec.why.mood_fit.mood || 'None'} (source: {rec.why.mood_fit.source})</div>
              )}
              {rec.why.novelty && (
                <div>Novelty: {rec.why.novelty.new_artist ? 'New artist' : 'Known artist'}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Player({ rec, premium }: { rec: RecommendPayload | null; premium: boolean }) {
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [sdkReady, setSdkReady] = useState(false)
  const [sdkError, setSdkError] = useState<string | null>(null)

  // Load SDK
  useEffect(() => {
    if (!premium) return
    if (document.getElementById('spotify-player')) return
    const script = document.createElement('script')
    script.id = 'spotify-player'
    script.src = 'https://sdk.scdn.co/spotify-player.js'
    script.async = true
    document.body.appendChild(script)
  }, [premium])

  useEffect(() => {
    if (!premium) return
    // @ts-ignore
    window.onSpotifyWebPlaybackSDKReady = async () => {
      setSdkReady(true)
      try {
        const tokenRes = await axios.get(`${API_BASE}/api/player/token`, { withCredentials: true })
        // @ts-ignore
        const player = new window.Spotify.Player({
          name: 'SOTD Web Player',
          getOAuthToken: (cb: any) => cb(tokenRes.data.access_token),
          volume: 0.8,
        })

        player.addListener('ready', ({ device_id }: any) => {
          setDeviceId(device_id)
        })
        player.addListener('not_ready', ({ device_id }: any) => {
          // device went offline
        })
        player.addListener('initialization_error', ({ message }: any) => setSdkError(message))
        player.addListener('authentication_error', ({ message }: any) => setSdkError(message))
        player.addListener('account_error', ({ message }: any) => setSdkError(message))

        player.connect()
      } catch (e: any) {
        setSdkError(e?.message || 'Failed to init player')
      }
    }
  }, [premium])

  useEffect(() => {
    const tryPlay = async () => {
      if (!rec) return
      if (!premium) return
      if (!deviceId) return
      try {
        await axios.post(
          `${API_BASE}/api/player/transfer`,
          { device_id: deviceId },
          { withCredentials: true }
        )
        await axios.put(
          `${API_BASE}/api/player/play`,
          { device_id: deviceId, uris: [rec.track_uri] },
          { withCredentials: true }
        )
      } catch (e) {
        // ignore, fallback UI will handle
      }
    }
    tryPlay()
  }, [rec, premium, deviceId])

  if (!rec) return null

  // Fallbacks when SDK not available, not premium, or errors
  if (premium && sdkReady && !sdkError) {
    return (
      <div style={{ marginTop: 12 }}>
        <p>Attempting playback via Web Playback SDK…</p>
      </div>
    )
  }

  if (rec.preview_url) {
    return (
      <div style={{ marginTop: 12 }}>
        <audio controls src={rec.preview_url} style={{ width: '100%' }} />
      </div>
    )
  }

  return (
    <div style={{ marginTop: 12 }}>
      <iframe
        title="Spotify Embed"
        src={`https://open.spotify.com/embed/track/${rec.track_id}`}
        width="100%"
        height="152"
        frameBorder="0"
        allow="encrypted-media"
      />
    </div>
  )
}
