import { useCallback, useEffect, useState } from 'react'
import { api, type SensorConfig, type SensorStatus, type SystemInfo } from '../lib/api'

const card = 'rounded-lg border border-soil-700/60 bg-soil-900/40 p-4'
const label = 'text-xs uppercase tracking-wide text-soil-400'
const btn = 'rounded bg-seed-500 px-3 py-1.5 text-sm font-semibold text-soil-900 disabled:opacity-40'
const btnGhost = 'rounded border border-soil-600 px-3 py-1.5 text-sm text-soil-200 disabled:opacity-40'

function Dot({ ok }: { ok: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-rose-500'}`} />
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <span className="text-soil-400">{k}</span>
      <span className="font-mono text-soil-100">{v}</span>
    </div>
  )
}

export function Control() {
  const [status, setStatus] = useState<SensorStatus | null>(null)
  const [cfg, setCfg] = useState<SensorConfig | null>(null)
  const [sys, setSys] = useState<SystemInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  // draft values for the editable fields
  const [length, setLength] = useState('')
  const [intensity, setIntensity] = useState(false)
  const [conf, setConf] = useState(0.4)

  const refreshStatus = useCallback(async () => {
    try { setStatus(await api.sensorStatus()) } catch (e) { setErr(String(e)) }
  }, [])

  const refreshSystem = useCallback(async () => {
    try {
      const s = await api.systemInfo()
      setSys(s); setConf(s.detector_conf)
    } catch (e) { setErr(String(e)) }
  }, [])

  useEffect(() => {
    refreshStatus(); refreshSystem()
    const t = setInterval(refreshStatus, 5000)
    return () => clearInterval(t)
  }, [refreshStatus, refreshSystem])

  const readConfig = async () => {
    setBusy(true); setErr(null); setNote(null)
    try {
      const r = await api.sensorConfig()
      setCfg(r.config)
      setLength(String(r.config.fixed_length_mm ?? ''))
      setIntensity(r.config.intensity_enabled)
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const apply = async () => {
    if (!cfg) return
    const patch: Record<string, unknown> = {}
    if (intensity !== cfg.intensity_enabled) patch.intensity_enabled = intensity
    const l = parseFloat(length)
    if (!Number.isNaN(l) && Math.abs(l - (cfg.fixed_length_mm ?? 0)) > 0.01) patch.fixed_length_mm = l
    if (!Object.keys(patch).length) { setNote('nothing to change'); return }
    if (!confirm(`Write to the sensor at ${status?.ip}?\n\n${JSON.stringify(patch, null, 2)}\n\nThis changes the device, not just this app.`)) return
    setBusy(true); setErr(null); setNote(null)
    try {
      const r = await api.setSensorConfig(patch)
      setCfg(r.after)
      setNote(r.changed.length ? `applied: ${r.changed.join(', ')}` : 'sensor already matched')
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const applyConf = async () => {
    setBusy(true); setErr(null); setNote(null)
    try {
      const r = await api.setDetectorConf(conf)
      setNote(`detection confidence now ${r.detector_conf}`)
      refreshSystem()
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const locked = !!status?.streaming

  return (
    <div className="flex flex-col gap-4">
      {err && <div className="rounded border border-rose-700 bg-rose-950/50 p-3 text-sm text-rose-200">{err}</div>}
      {note && <div className="rounded border border-emerald-800 bg-emerald-950/40 p-3 text-sm text-emerald-200">{note}</div>}
      {locked && (
        <div className="rounded border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-200">
          A session is streaming. The sensor only accepts one SDK connection, so config is read-only until it stops.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className={card}>
          <h2 className="mb-3 text-sm font-semibold text-soil-100">Sensor</h2>
          {status ? (
            <>
              <Row k="ip" v={status.ip} />
              <Row k="reachable" v={<><Dot ok={status.reachable} /> {status.reachable ? 'yes' : 'no'}</>} />
              <Row k="streaming" v={status.streaming ? 'yes — session active' : 'idle'} />
              <div className="mt-2 border-t border-soil-700/60 pt-2">
                {Object.entries(status.ports).map(([n, ok]) => (
                  <Row key={n} k={`port ${n}`} v={<><Dot ok={ok} /> {ok ? 'open' : 'closed'}</>} />
                ))}
              </div>
            </>
          ) : <p className="text-sm text-soil-400">probing…</p>}
        </section>

        <section className={card}>
          <h2 className="mb-3 text-sm font-semibold text-soil-100">This machine</h2>
          {sys ? (
            <>
              <Row k="host" v={`${sys.host} (${sys.machine})`} />
              <Row k="model" v={sys.model ?? 'classical fallback'} />
              <Row k="task" v={sys.model_task ?? '—'} />
              <Row k="gpu" v={sys.gpu ?? (sys.cuda ? 'cuda' : 'cpu only')} />
              <Row k="torch" v={sys.torch ?? '—'} />
              <Row k="ultralytics" v={sys.ultralytics ?? '—'} />
              <Row k="opencv / numpy" v={`${sys.opencv ?? '—'} / ${sys.numpy ?? '—'}`} />
              <Row k="python" v={sys.python} />
              {sys.retired_models.length > 0 && (
                <Row k="retired" v={<span className="text-amber-300">{sys.retired_models.join(', ')}</span>} />
              )}
            </>
          ) : <p className="text-sm text-soil-400">loading…</p>}
        </section>
      </div>

      <section className={card}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-soil-100">Sensor configuration</h2>
          <button className={btnGhost} onClick={readConfig} disabled={busy || locked}>
            {cfg ? 'Re-read' : 'Read from sensor'}
          </button>
        </div>
        {!cfg ? (
          <p className="text-sm text-soil-400">
            Not read yet — opening an SDK connection takes about 1.5 s, so it is not done automatically.
          </p>
        ) : (
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <Row k="scan mode" v={cfg.scan_mode_is_surface ? `surface (${cfg.scan_mode})` : `NOT surface (${cfg.scan_mode})`} />
              <Row k="generation" v={cfg.is_fixed_length ? 'fixed length' : `type ${cfg.generation_type}`} />
              <Row k="eth: surface" v={String(cfg.eth_source_surface ?? '—')} />
              <Row k="eth: intensity" v={String(cfg.eth_source_intensity ?? '—')} />
            </div>
            <div className="flex flex-col gap-3">
              <label className="flex items-center gap-2 text-sm text-soil-200">
                <input type="checkbox" checked={intensity} disabled={locked}
                       onChange={e => setIntensity(e.target.checked)} />
                intensity enabled
                <span className="text-xs text-soil-500">(detector needs it)</span>
              </label>
              <div>
                <div className={label}>surface fixed length (mm)</div>
                <input className="mt-1 w-40 rounded bg-soil-800 px-2 py-1 font-mono text-sm text-soil-100"
                       value={length} disabled={locked} onChange={e => setLength(e.target.value)} />
              </div>
              <button className={btn} onClick={apply} disabled={busy || locked}>Write to sensor</button>
              <p className="text-xs text-soil-500">
                Writes go to the device and persist. Current values were captured before the first
                live run in <code>data/sensor-config-snapshot.json</code>.
              </p>
            </div>
          </div>
        )}
      </section>

      <section className={card}>
        <h2 className="mb-3 text-sm font-semibold text-soil-100">Detector tuning</h2>
        <div className="flex flex-wrap items-center gap-4">
          <input type="range" min={0.05} max={0.9} step={0.05} value={conf}
                 onChange={e => setConf(parseFloat(e.target.value))} className="w-64" />
          <span className="font-mono text-sm text-soil-100">conf = {conf.toFixed(2)}</span>
          <button className={btn} onClick={applyConf} disabled={busy}>Apply</button>
        </div>
        <p className="mt-2 text-xs text-soil-500">
          Applies to the next frame detected. Measured on the curated set: 0.25 gives 95% recall
          at 3.7 mm MAE, 0.40 gives 92% at 3.3 mm, 0.55 gives 88% at 3.2 mm. Not persisted across
          a restart.
        </p>
      </section>
    </div>
  )
}
