import { useEffect, useRef, useState } from 'react'
import type { Head } from './api'

export type WsEvent =
  | { type: 'frame_processed'; session_id: number; frame_idx: number; heads: Head[]
      n_candidates: number; overlay_url: string; totals: { frames: number; heads: number } }
  | { type: 'frame_failed'; session_id: number; frame_idx: number; error: string }
  | { type: 'session_state'; session_id: number; state: string; frames?: number; heads?: number }

/** One reconnecting socket for the app. The server is push-only; the UI
 *  re-syncs over REST on reconnect, so dropped events are never fatal. */
export function useWs(onEvent: (e: WsEvent) => void) {
  const [connected, setConnected] = useState(false)
  const cb = useRef(onEvent)
  cb.current = onEvent

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout>
    let watchdog: ReturnType<typeof setInterval>
    let lastMsg = Date.now()
    let closed = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => {
        setConnected(true)
        lastMsg = Date.now()
        // A severed socket can sit in OPEN forever and never fire onclose, so
        // silence — not socket state — is what we treat as dead. The server
        // heartbeats every 10s; 35s of nothing means reconnect.
        watchdog = setInterval(() => {
          if (Date.now() - lastMsg > 35000) { setConnected(false); ws?.close() }
        }, 5000)
      }
      ws.onmessage = (m) => {
        lastMsg = Date.now()
        let e
        try { e = JSON.parse(m.data) } catch { return }
        if (e.type === 'heartbeat') return
        cb.current(e)
      }
      ws.onclose = () => {
        setConnected(false)
        clearInterval(watchdog)
        if (!closed) retry = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws?.close()
    }
    connect()
    return () => { closed = true; clearTimeout(retry); clearInterval(watchdog); ws?.close() }
  }, [])

  return connected
}
