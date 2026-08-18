import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type Head, type Session, type Validation } from '../lib/api'
import { Stat } from '../components/Stat'
import { ValidationScatter } from '../components/ValidationScatter'

export function SessionDetail() {
  const { id } = useParams()
  const sid = Number(id)
  const [session, setSession] = useState<Session | null>(null)
  const [heads, setHeads] = useState<Head[]>([])
  const [val, setVal] = useState<Validation | null>(null)

  useEffect(() => {
    api.sessions().then((all) => setSession(all.find((s) => s.id === sid) ?? null)).catch(() => {})
    api.heads(sid).then(setHeads).catch(() => {})
    api.validation(sid).then(setVal).catch(() => {})
  }, [sid])

  const dias = heads.map((h) => h.dia_mm)
  const mean = dias.length ? dias.reduce((a, b) => a + b, 0) / dias.length : null
  const st = val?.stats

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="font-mono text-lg text-soil-50">Session #{sid}</h2>
        {session && (
          <p className="mt-1 font-mono text-xs text-soil-300">
            {session.mode} · {session.source} · {new Date(session.started_at).toLocaleString()}
            {session.notes && ` · ${session.notes}`}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="frames" value={session?.frame_count ?? 0} />
        <Stat label="heads" value={heads.length} accent />
        <Stat label="mean Ø" value={mean ? `${mean.toFixed(1)} mm` : '—'} />
        <Stat label="range" value={dias.length ? `${Math.min(...dias).toFixed(0)}–${Math.max(...dias).toFixed(0)} mm` : '—'} />
      </div>

      <section>
        <h3 className="mb-3 text-xs tracking-wider text-soil-300 uppercase">Validation vs caliper</h3>
        {st && st.n > 0 ? (
          <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-3 gap-3">
                <Stat label="MAE" value={`${st.mae_mm!.toFixed(1)} mm`} accent />
                <Stat label="bias" value={`${st.bias_mm! > 0 ? '+' : ''}${st.bias_mm!.toFixed(1)} mm`} />
                <Stat label="worst" value={`${st.max_abs_err_mm!.toFixed(1)} mm`} />
              </div>
              <div className="overflow-x-auto rounded-lg border border-soil-800">
                <table className="w-full text-sm">
                  <thead className="bg-soil-900/60 text-xs tracking-wider text-soil-300 uppercase">
                    <tr>{['plant', 'caliper', 'ours', 'Δ'].map((h) =>
                      <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {val!.rows.map((r, i) => {
                      const d = r.ours_mm === null ? null : r.ours_mm - r.caliper_mm
                      return (
                        <tr key={i} className="border-t border-soil-800/60">
                          <td className="px-3 py-1.5 font-mono">{r.plant_tag}</td>
                          <td className="px-3 py-1.5 font-mono tabular-nums">{r.caliper_mm.toFixed(1)}</td>
                          <td className="px-3 py-1.5 font-mono tabular-nums">{r.ours_mm?.toFixed(1) ?? '—'}</td>
                          <td className={`px-3 py-1.5 font-mono tabular-nums ${
                            d === null ? 'text-soil-600' : Math.abs(d) <= 5 ? 'text-leaf-500' : 'text-alert-500'}`}>
                            {d === null ? 'unmatched' : `${d > 0 ? '+' : ''}${d.toFixed(1)}`}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <ValidationScatter rows={val!.rows} />
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-soil-800 px-4 py-6 text-sm text-soil-600">
            No caliper readings logged yet. On the Live page, tap a detected head to record one.
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-xs tracking-wider text-soil-300 uppercase">
          Detected heads ({heads.length})
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {heads.map((h) => (
            <figure key={h.id} className="overflow-hidden rounded-lg border border-soil-800 bg-black/40">
              <img src={api.overlayUrl(sid, h.frame_idx)} alt={`frame ${h.frame_idx}`}
                loading="lazy" className="h-32 w-full object-cover" />
              <figcaption className="flex items-baseline gap-2 px-2 py-1.5">
                <span className="font-mono text-base font-semibold text-seed-400 tabular-nums">
                  {h.dia_mm.toFixed(0)}<span className="text-[10px] text-soil-300"> mm</span>
                </span>
                <span className="ml-auto font-mono text-[10px] text-soil-600">f{h.frame_idx}</span>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>
    </div>
  )
}
