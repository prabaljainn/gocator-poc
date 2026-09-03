import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Head, type Health } from '../lib/api'
import { useWs, type WsEvent } from '../lib/ws'
import { Stat } from '../components/Stat'
import { GroundTruthDialog } from '../components/GroundTruthDialog'

type FeedItem = { frameIdx: number; heads: Head[]; overlay: string; at: number }

export function Live() {
  const [health, setHealth] = useState<Health | null>(null)
  const [feed, setFeed] = useState<FeedItem[]>([])
  const [latest, setLatest] = useState<FeedItem | null>(null)
  const [mode, setMode] = useState<'live' | 'replay'>('live')
  const [source, setSource] = useState('tobetsu-data-20260730-1416.rec')
  const [limit, setLimit] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [gtHead, setGtHead] = useState<Head | null>(null)
  const seen = useRef(new Set<number>())
  const shownSession = useRef<number | null>(null)

  const onEvent = useCallback((e: WsEvent) => {
    // Frame indices restart at 0 every session, so dedup has to be scoped to one
    // session — otherwise a second session's frames all look already-seen.
    if (e.session_id !== shownSession.current) {
      shownSession.current = e.session_id
      seen.current.clear()
      setFeed([])
      setLatest(null)
    }
    if (e.type === 'frame_processed') {
      if (seen.current.has(e.frame_idx)) return
      seen.current.add(e.frame_idx)
      const item = { frameIdx: e.frame_idx, heads: e.heads, overlay: e.overlay_url, at: Date.now() }
      setLatest(item)
      if (e.heads.length) setFeed((f) => [item, ...f].slice(0, 60))
    }
    if (e.type === 'session_state') refresh()
  }, [])
  const connected = useWs(onEvent)

  const refresh = () => api.health().then(setHealth).catch(() => {})
  useEffect(() => { refresh(); const t = setInterval(refresh, 3000); return () => clearInterval(t) }, [])

  // WS only carries events from now on, so hydrate the last session's results —
  // otherwise reloading the page mid-campaign shows empty panels.
  useEffect(() => {
    let cancelled = false
    api.sessions().then(async (all) => {
      const last = all[0]
      if (!last || cancelled) return
      const heads = await api.heads(last.id)
      if (cancelled || !heads.length) return
      const byFrame = new Map<number, Head[]>()
      for (const h of heads) byFrame.set(h.frame_idx, [...(byFrame.get(h.frame_idx) ?? []), h])
      const items = [...byFrame.entries()]
        .sort((a, b) => b[0] - a[0])
        .map(([frameIdx, hs]) => ({
          frameIdx, heads: hs, overlay: api.overlayUrl(last.id, frameIdx), at: 0,
        }))
      if (shownSession.current !== null) return  // a live session already took over
      shownSession.current = last.id
      setFeed((f) => (f.length ? f : items.slice(0, 60)))
      setLatest((l) => l ?? items[0])
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const [fps, setFps] = useState<number>(2.0)

  const start = async () => {
    setBusy(true); setErr(null); seen.current.clear(); setFeed([]); setLatest(null)
    shownSession.current = null
    try {
      await api.start(mode === 'live'
        ? { mode: 'live', source: health?.sensor_ip ?? '192.168.1.10', fps }
        : { mode: 'replay', source, limit: limit ? Number(limit) : null, fps })
      refresh()
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }
  const stop = async () => {
    if (health?.session_id) { await api.stop(health.session_id).catch(() => {}); refresh() }
  }

  const togglePause = async () => {
    if (!health?.session_id) return
    try {
      if (health.paused) {
        await api.resume(health.session_id)
      } else {
        await api.pause(health.session_id)
      }
      refresh()
    } catch (e) { setErr(String(e)) }
  }

  const stepNext = async () => {
    if (!health?.session_id) return
    try {
      await api.step(health.session_id)
    } catch (e) { setErr(String(e)) }
  }

  const changeSpeed = async (newFps: number) => {
    setFps(newFps)
    if (health?.session_id && health.running) {
      try {
        await api.setSpeed(health.session_id, newFps)
      } catch (e) { setErr(String(e)) }
    }
  }

  // Keyboard shortcut to Pause/Resume with Space or Step with S/ArrowRight
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT'].includes((e.target as HTMLElement).tagName)) return
      if (e.key === ' ' && health?.running) {
        e.preventDefault()
        togglePause()
      } else if ((e.key === 'ArrowRight' || e.key === 's' || e.key === 'S') && health?.running && health?.paused) {
        e.preventDefault()
        stepNext()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [health?.running, health?.paused, health?.session_id])

  const running = health?.running ?? false
  const isPaused = health?.paused ?? false
  const dias = feed.flatMap((f) => f.heads.map((h) => h.dia_mm))
  const meanDia = dias.length ? dias.reduce((a, b) => a + b, 0) / dias.length : null

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-soil-800 bg-soil-900/60 p-4">
        <div className="flex flex-col gap-1 text-xs text-soil-300">
          Mode
          <div className="flex overflow-hidden rounded border border-soil-800">
            {(['live', 'replay'] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} disabled={running}
                className={`px-3 py-1.5 text-sm ${mode === m
                  ? 'bg-seed-500 font-semibold text-soil-900'
                  : 'text-soil-300 hover:bg-soil-800/60'} disabled:opacity-50`}>
                {m === 'live' ? 'Sensor' : 'Replay'}
              </button>
            ))}
          </div>
        </div>
        {mode === 'live' ? (
          <div className="flex flex-col gap-1 text-xs text-soil-300">
            Sensor
            <div className="rounded border border-soil-800 px-3 py-1.5 font-mono text-sm text-soil-50">
              {health?.sensor_ip ?? '—'}
              {health && !health.live_acquisition && (
                <span className="ml-2 text-alert-500">GoSDK unavailable</span>
              )}
            </div>
          </div>
        ) : (
          <>
            <label className="flex flex-col gap-1 text-xs text-soil-300">
              Source (.rec on the server)
              <input value={source} onChange={(e) => setSource(e.target.value)} disabled={running}
                className="w-80 rounded border border-soil-800 bg-soil-900 px-2 py-1.5 font-mono text-sm
                           text-soil-50 disabled:opacity-50" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-soil-300">
              Frame limit
              <input value={limit} onChange={(e) => setLimit(e.target.value.replace(/\D/g, ''))}
                placeholder="all" disabled={running}
                className="w-24 rounded border border-soil-800 bg-soil-900 px-2 py-1.5 font-mono text-sm
                           text-soil-50 disabled:opacity-50" />
            </label>
          </>
        )}

        {/* Speed tuning selector */}
        <div className="flex flex-col gap-1 text-xs text-soil-300">
          Speed
          <select
            value={fps}
            onChange={(e) => changeSpeed(Number(e.target.value))}
            className="rounded border border-soil-800 bg-soil-900 px-2 py-1.5 font-mono text-sm text-soil-50 focus:outline-none"
          >
            <option value={0.5}>0.5 FPS (2s / frame)</option>
            <option value={1.0}>1.0 FPS (Slow)</option>
            <option value={2.0}>2.0 FPS (Observable)</option>
            <option value={5.0}>5.0 FPS (Fast)</option>
            <option value={0}>Max Speed (Uncapped)</option>
          </select>
        </div>

        {/* Playback Controls */}
        <div className="flex items-center gap-2">
          {running ? (
            <>
              <button
                onClick={togglePause}
                className={`rounded px-4 py-2 text-sm font-semibold text-soil-900 shadow transition-colors ${
                  isPaused ? 'bg-yellow-400 hover:bg-yellow-300' : 'bg-soil-200 hover:bg-white'
                }`}
                title="Shortcut: Space"
              >
                {isPaused ? '▶ Resume' : '⏸ Pause'}
              </button>

              {isPaused && (
                <button
                  onClick={stepNext}
                  className="rounded border border-soil-700 bg-soil-800 px-3 py-2 text-sm font-semibold text-soil-100 hover:bg-soil-700"
                  title="Step 1 frame forward (Shortcut: ArrowRight or S)"
                >
                  ⏭ Step
                </button>
              )}

              <button
                onClick={stop}
                className="rounded bg-alert-500 px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                Stop
              </button>
            </>
          ) : (
            <button
              onClick={start}
              disabled={busy}
              className="rounded bg-seed-500 px-5 py-2 text-sm font-semibold text-soil-900 hover:bg-seed-400 disabled:opacity-50"
            >
              {busy ? 'Starting…' : 'Start session'}
            </button>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3">
          {running && isPaused && (
            <span className="rounded bg-yellow-400/20 border border-yellow-400/50 px-2 py-0.5 text-xs font-bold text-yellow-400 animate-pulse">
              PAUSED
            </span>
          )}
          <span className={`flex items-center gap-2 text-xs ${connected ? 'text-leaf-500' : 'text-alert-500'}`}>
            <span className={`inline-block h-2 w-2 rounded-full ${connected ? 'bg-leaf-500' : 'bg-alert-500'}`} />
            {connected ? 'live' : 'reconnecting…'}
          </span>
        </div>
      </div>

      {err && <div className="rounded border border-alert-500/50 bg-alert-500/10 px-4 py-2 text-sm text-alert-500">{err}</div>}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="frames" value={health?.frames_done ?? 0} />
        <Stat label="heads" value={health?.heads_found ?? 0} accent />
        <Stat label="mean Ø" value={meanDia ? `${meanDia.toFixed(0)} mm` : '—'} />
        <Stat label="disk free" value={`${health?.disk_free_gb ?? '—'} GB`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-lg border border-soil-800 bg-black/40 p-2">
          {latest ? (
            <figure className="flex flex-col gap-2">
              <img src={latest.overlay} alt={`frame ${latest.frameIdx}`}
                className="max-h-[62vh] w-full rounded object-contain" />
              <figcaption className="px-1 pb-1 font-mono text-xs text-soil-300">
                frame {latest.frameIdx} · {latest.heads.length} head(s)
                {latest.heads.length > 0 && ` · ${latest.heads.map((h) => `${h.dia_mm.toFixed(0)}mm`).join(', ')}`}
              </figcaption>
            </figure>
          ) : (
            <div className="flex h-64 items-center justify-center text-sm text-soil-600">
              {running ? 'waiting for the first frame…' : 'start a session to see frames'}
            </div>
          )}
        </div>

        <div className="flex max-h-[70vh] flex-col overflow-hidden rounded-lg border border-soil-800">
          <div className="border-b border-soil-800 bg-soil-900/60 px-3 py-2 text-xs tracking-wider text-soil-300 uppercase">
            detected heads — tap to log a caliper reading
          </div>
          <div className="flex-1 overflow-y-auto">
            {feed.length === 0 && <p className="p-4 text-sm text-soil-600">nothing yet</p>}
            {feed.map((f) =>
              f.heads.map((h) => (
                <button key={h.id ?? `${f.frameIdx}-${h.cx_mm}`} onClick={() => setGtHead(h)}
                  className="flex w-full items-baseline gap-3 border-b border-soil-800/60 px-3 py-2
                             text-left hover:bg-soil-800/40">
                  <span className="font-mono text-lg font-semibold text-seed-400 tabular-nums">
                    {h.dia_mm.toFixed(0)}<span className="text-xs text-soil-300"> mm</span>
                  </span>
                  <span className="font-mono text-xs text-soil-300">frame {f.frameIdx}</span>
                  <span className="ml-auto font-mono text-xs text-soil-600">tex {h.tex_in?.toFixed(0)}</span>
                </button>
              )),
            )}
          </div>
        </div>
      </div>

      {gtHead && health?.session_id && (
        <GroundTruthDialog head={gtHead} sessionId={health.session_id} onClose={() => setGtHead(null)} />
      )}
    </div>
  )
}
