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
    let keepalive: ReturnType<typeof setInterval>
    let closed = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => {
        setConnected(true)
        keepalive = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 20000)
      }
      ws.onmessage = (m) => { try { cb.current(JSON.parse(m.data)) } catch { /* ignore */ } }
      ws.onclose = () => {
        setConnected(false)
        clearInterval(keepalive)
        if (!closed) retry = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws?.close()
    }
    connect()
    return () => { closed = true; clearTimeout(retry); clearInterval(keepalive); ws?.close() }
  }, [])

  return connected
}
