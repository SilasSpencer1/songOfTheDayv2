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
  const [bgGrad, setBgGrad] = useState<string>('radial-gradient(800px 400px at 20% 10%, rgba(26,36,48,.7) 0%, rgba(0,0,0,0) 60%), radial-gradient(600px 300px at 80% 90%, rgba(42,20,53,.7) 0%, rgba(0,0,0,0) 60%)')
  const [albumBg, setAlbumBg] = useState<string | null>(null)
  const [showAbout, setShowAbout] = useState(false)
  const [showSettings, setShowSettings] = useState(false)

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
    // Force a fresh Spotify auth dialog to avoid silently reusing a cached login
    window.location.href = `${API_BASE}/auth/login?force=1`
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
      // Update background gradient and blurred bg from album art (simple average color)
      if (res.data?.album_image_url) {
        setAlbumBg(res.data.album_image_url)
        const img = new Image()
        img.crossOrigin = 'anonymous'
        img.src = res.data.album_image_url
        img.onload = () => {
          try {
            const cvs = document.createElement('canvas')
            cvs.width = 40; cvs.height = 40
            const ctx = cvs.getContext('2d')!
            ctx.drawImage(img, 0, 0, 40, 40)
            const data = ctx.getImageData(0, 0, 40, 40).data
            let r=0,g=0,b=0, n=0
            for (let i=0;i<data.length;i+=4){ r+=data[i]; g+=data[i+1]; b+=data[i+2]; n++ }
            r=Math.round(r/n); g=Math.round(g/n); b=Math.round(b/n)
            const c1 = `rgba(${r},${g},${b},0.5)`
            const c2 = `rgba(${Math.max(0,r-40)},${Math.max(0,g-40)},${Math.max(0,b-40)},0.5)`
            setBgGrad(`radial-gradient(900px 500px at 15% 20%, ${c1} 0%, transparent 60%), radial-gradient(700px 350px at 85% 85%, ${c2} 0%, transparent 60%)`)
          } catch {}
        }
      }
    } catch (e: any) {
      setError(e?.response?.data?.error || e.message)
      setRec(null)
    } finally {
      setLoading(false)
    }
  }

  const onLogout = async () => {
    try { await axios.post(`${API_BASE}/auth/logout`, {}, { withCredentials: true }) } catch {}
    window.location.reload()
  }

  const onClearCache = async () => {
    try { await axios.post(`${API_BASE}/auth/logout`, {}, { withCredentials: true }) } catch {}
    try { localStorage.clear(); sessionStorage.clear() } catch {}
    // Sign out of Spotify in the SAME tab to avoid SSO reuse
    window.location.href = 'https://accounts.spotify.com/logout'
  }

  return (
    <div style={{ minHeight:'100%', position: 'relative' }}>
      {albumBg && (
        <div style={{ position: 'fixed', inset: 0, backgroundImage: `url(${albumBg})`, backgroundSize: 'cover', backgroundPosition: 'center', filter: 'blur(40px) saturate(120%)', opacity: .35, pointerEvents: 'none', zIndex: 0 }} />
      )}
      <div style={{ position: 'fixed', inset: 0, background: bgGrad, pointerEvents: 'none', zIndex: 0 }} />
      <div style={{ maxWidth: 960, margin: '0 auto', padding: 24 }}>
        <div className="glass" style={{ padding:16, display:'flex', alignItems:'center', justifyContent:'space-between', position: 'relative', zIndex: 1 }}>
          <div style={{ display:'flex', alignItems:'center', gap:12 }}>
            <div style={{ width:36, height:36, borderRadius:10, background:'rgba(255,255,255,0.15)' }} />
            <h2 style={{ margin:0 }}>Song of the Day</h2>
          </div>
          <div style={{ display:'flex', gap:8 }}>
            <button className="btn" onClick={() => setShowAbout(s => !s)}>About</button>
            <button className="btn" onClick={() => setShowSettings(s => !s)}>Settings</button>
          </div>
        </div>
        {showAbout && (
          <div className="glass fade-up" style={{ padding:16, marginTop:12, position: 'relative', zIndex: 1 }}>
            <h3 style={{ marginTop:0 }}>About</h3>
            <p>Our goal is to find that one track you’ll keep on repeat the rest of the day. We learn from your listening and your quick feedback to improve each pick.</p>
            <p style={{ opacity:.9 }}>
              Under the hood, we train a tiny online model per mood using logistic regression. Each candidate track is featurized by:
            </p>
            <ul>
              <li>Genre fit with your chosen mood (overlap of artist genres with a mood genre set)</li>
              <li>Popularity proximity to a mood target (we don’t just chase the most popular)</li>
              <li>Recency bias tuned per mood (some moods prefer fresher releases)</li>
            </ul>
            <p style={{ opacity:.9 }}>
              Your thumbs-up/down updates the weights immediately, so the next recommendation adapts to you. We never call restricted Spotify endpoints; everything is heuristics plus your signal.
            </p>
          </div>
        )}
        {showSettings && (
          <div className="glass" style={{ padding:16, marginTop:12, display:'flex', gap:8, flexWrap:'wrap', position: 'relative', zIndex: 1 }}>
            <button className="btn" onClick={onLogout}>Log out</button>
            <button className="btn" onClick={onClearCache}>Clear cache</button>
          </div>
        )}
      {!me ? (
        <LoginGate onLogin={onLogin} />
      ) : (
        <div style={{ display:'grid', gridTemplateColumns:'1fr', gap:16, marginTop:16, position: 'relative', zIndex: 1 }}>
          <div className="glass fade-up" style={{ padding:16 }}>
            <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
              <div>Welcome, {me.display_name}</div>
              <MoodSelector mood={mood} onChange={setMood} />
            </div>
          </div>
          <div className="glass fade-up" style={{ padding: 16 }}>
            <RecommendCard onRecommend={onRecommend} loading={loading} error={error} rec={rec} />
            <Player rec={rec} premium={me.premium} />
          </div>
        </div>
      )}
      </div>
    </div>
  )
}

function LoginGate({ onLogin }: { onLogin: () => void }) {
  return (
    <div className="glass" style={{ display: 'flex', flexDirection: 'column', gap: 12, padding:16, marginTop:16 }}>
      <p>Connect your Spotify account to get a daily recommendation.</p>
      <button onClick={onLogin} className="btn">Connect Spotify</button>
    </div>
  )
}

function MoodSelector({ mood, onChange }: { mood: Mood; onChange: (m: Mood) => void }) {
  const moods: Mood[] = [null, 'Happy', 'Sad', 'Energetic', 'Calm']
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {moods.map((m) => (
        <button
          key={String(m)}
          onClick={() => onChange(m)}
          style={{
            padding: '6px 10px',
            borderRadius: 16,
            border: '1px solid rgba(255,255,255,0.22)',
            background: m === mood ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.06)',
            color: '#fff',
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
    <div>
      <button onClick={onRecommend} disabled={loading} className="btn fade-up">
        {loading ? 'Loading…' : 'Get Song of the Day'}
      </button>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {rec && (rec as any).already_picked && (
        <div className="glass" style={{ padding:12, marginTop:8 }}>
          You already got today's song. A new pick will be available after 12:00am ET.
        </div>
      )}
      {rec && (
        <div style={{ marginTop: 16 }}>
          <div className="hero-row">
            {rec.album_image_url && (
              <div className="album-hero">
                <img src={rec.album_image_url} alt={rec.name} />
              </div>
            )}
            <div className="fade-up" style={{ minWidth: 240 }}>
              <div className="subtitle">{rec.artist}</div>
              <div className="title-xl">{rec.name}</div>
              <a href={rec.spotify_url} target="_blank" rel="noreferrer">Open in Spotify</a>
              <div style={{ marginTop:8, display:'flex', gap:8, flexWrap:'wrap' }}>
                <LikeButtonOnly rec={rec} />
              </div>
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
          <Feedback rec={rec} />
        </div>
      )}
    </div>
  )
}

function Player({ rec, premium }: { rec: RecommendPayload | null; premium: boolean }) {
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [sdkReady, setSdkReady] = useState(false)
  const [sdkError, setSdkError] = useState<string | null>(null)
  const playerRef = useRef<any>(null)
  const [sdkState, setSdkState] = useState<any>(null)
  const [sdkProgress, setSdkProgress] = useState<number>(0)
  const [sdkDuration, setSdkDuration] = useState<number>(0)
  const [sdkPaused, setSdkPaused] = useState<boolean>(true)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [progress, setProgress] = useState<number>(0)
  const [duration, setDuration] = useState<number>(0)
  const [paused, setPaused] = useState(true)

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

        playerRef.current = player
        player.addListener('ready', ({ device_id }: any) => {
          setDeviceId(device_id)
        })
        player.addListener('not_ready', ({ device_id }: any) => {
          // device went offline
        })
        player.addListener('initialization_error', ({ message }: any) => setSdkError(message))
        player.addListener('authentication_error', ({ message }: any) => setSdkError(message))
        player.addListener('account_error', ({ message }: any) => setSdkError(message))
        player.addListener('player_state_changed', (state: any) => {
          if (!state) return
          setSdkState(state)
          setSdkPaused(state.paused)
          setSdkProgress((state.position || 0) / 1000)
          setSdkDuration((state.duration || 0) / 1000)
        })

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
      <div className="fade-up" style={{ marginTop: 16 }}>
        <div style={{ display:'flex', alignItems:'center', gap:12, flexWrap:'wrap' }}>
          <button className="btn" onClick={()=>playerRef.current?.togglePlay()}>{sdkPaused ? 'Play' : 'Pause'}</button>
        </div>
      </div>
    )
  }

  if (rec.preview_url) {
    return (
      <div className="glass" style={{ marginTop: 12, padding:16 }}>
        <audio ref={audioRef} src={rec.preview_url} onTimeUpdate={(e)=>{
          const a = e.currentTarget
          setProgress(a.currentTime)
          setDuration(a.duration || 0)
          setPaused(a.paused)
        }} style={{ display:'none' }} />
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <button className="btn" onClick={()=>{ if (!audioRef.current) return; if (audioRef.current.paused) { audioRef.current.play() } else { audioRef.current.pause() } }}>{paused ? 'Play' : 'Pause'}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="glass" style={{ marginTop: 12, padding:16 }}>
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

function Feedback({ rec }: { rec: RecommendPayload }) {
  const [status, setStatus] = useState<string | null>(null)
  const send = async (score: -1|0|1) => {
    setStatus(null)
    try {
      await axios.post(`${API_BASE}/api/feedback`, { track_id: rec.track_id, mood: (rec as any)?.why?.mood_fit?.mood || null, score }, { withCredentials: true })
      setStatus('Thanks for the feedback!')
    } catch (e: any) {
      setStatus(e?.response?.data?.error || 'Failed to send feedback')
    }
  }
  return (
    <div style={{ marginTop:12, display:'flex', alignItems:'center', gap:8 }}>
      <span>Was this a good pick?</span>
      <button className="btn" onClick={()=>send(1)}>👍</button>
      <button className="btn" onClick={()=>send(0)}>😐</button>
      <button className="btn" onClick={()=>send(-1)}>👎</button>
      {status && <span style={{ marginLeft:8, opacity:.85 }}>{status}</span>}
    </div>
  )
}

function LikeButtonOnly({ rec }: { rec: RecommendPayload }) {
  const [msg, setMsg] = useState<string | null>(null)
  const like = async () => {
    try {
      await axios.post(`${API_BASE}/api/like`, { track_id: rec.track_id }, { withCredentials: true })
      setMsg('Saved to Liked Songs')
    } catch (e:any) { setMsg('Needs scope or failed') }
  }
  return (
    <>
      <button className="btn" onClick={like}>Add to Liked Songs</button>
      {msg && <span style={{ opacity:.8 }}>{msg}</span>}
    </>
  )
}
