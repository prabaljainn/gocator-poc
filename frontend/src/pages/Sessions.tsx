import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Session } from '../lib/api'

export function Sessions() {
  const [rows, setRows] = useState<Session[]>([])
  useEffect(() => { api.sessions().then(setRows).catch(() => {}) }, [])

  if (!rows.length) return <p className="text-sm text-soil-600">No sessions recorded yet.</p>

  return (
    <div className="overflow-x-auto rounded-lg border border-soil-800">
      <table className="w-full text-sm">
        <thead className="bg-soil-900/60 text-xs tracking-wider text-soil-300 uppercase">
          <tr>
            {['id', 'started', 'mode', 'source', 'frames', 'heads', 'state'].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} className="border-t border-soil-800/60 hover:bg-soil-800/30">
              <td className="px-3 py-2">
                <Link to={`/sessions/${s.id}`} className="font-mono text-seed-400 hover:underline">#{s.id}</Link>
              </td>
              <td className="px-3 py-2 font-mono text-xs text-soil-300">
                {new Date(s.started_at).toLocaleString()}
              </td>
              <td className="px-3 py-2">{s.mode}</td>
              <td className="max-w-[22ch] truncate px-3 py-2 font-mono text-xs text-soil-300" title={s.source}>
                {s.source}
              </td>
              <td className="px-3 py-2 font-mono tabular-nums">{s.frame_count}</td>
              <td className="px-3 py-2 font-mono font-semibold text-seed-400 tabular-nums">{s.head_count}</td>
              <td className="px-3 py-2">
                <span className={`rounded px-2 py-0.5 text-xs ${
                  s.state === 'done' ? 'bg-leaf-500/15 text-leaf-500'
                  : s.state === 'running' ? 'bg-seed-500/15 text-seed-400'
                  : 'bg-alert-500/15 text-alert-500'}`}>{s.state}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
