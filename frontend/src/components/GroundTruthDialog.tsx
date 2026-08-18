import { useEffect, useRef, useState } from 'react'
import { api, type Head } from '../lib/api'

/** Log a caliper reading against one detected head. Manual matching is
 *  deliberate (D9) — validation numbers must be unambiguous. */
export function GroundTruthDialog(
  { head, sessionId, onClose }: { head: Head; sessionId: number; onClose: () => void },
) {
  const [tag, setTag] = useState('')
  const [mm, setMm] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const first = useRef<HTMLInputElement>(null)

  useEffect(() => { first.current?.focus() }, [])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const save = async () => {
    if (!tag.trim() || !mm) { setErr('plant tag and caliper reading are both required'); return }
    setSaving(true); setErr(null)
    try {
      await api.addGroundTruth({
        session_id: sessionId, plant_tag: tag.trim(),
        caliper_mm: Number(mm), head_id: head.id,
      })
      onClose()
    } catch (e) { setErr(String(e)); setSaving(false) }
  }

  const delta = mm ? head.dia_mm - Number(mm) : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-lg border border-soil-800 bg-soil-900 p-5"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="text-sm tracking-wider text-soil-300 uppercase">Log caliper reading</h2>
        <p className="mt-2 font-mono text-sm text-soil-50">
          pipeline measured <span className="text-lg font-semibold text-seed-400">{head.dia_mm.toFixed(1)} mm</span>
          <span className="text-soil-600"> · frame {head.frame_idx}</span>
        </p>

        <label className="mt-4 flex flex-col gap-1 text-xs text-soil-300">
          Plant tag
          <input ref={first} value={tag} onChange={(e) => setTag(e.target.value)}
            placeholder="e.g. A-12"
            className="rounded border border-soil-800 bg-soil-900 px-3 py-2 font-mono text-base text-soil-50" />
        </label>
        <label className="mt-3 flex flex-col gap-1 text-xs text-soil-300">
          Caliper diameter (mm)
          <input value={mm} onChange={(e) => setMm(e.target.value.replace(/[^\d.]/g, ''))}
            inputMode="decimal" placeholder="e.g. 74.5" onKeyDown={(e) => e.key === 'Enter' && save()}
            className="rounded border border-soil-800 bg-soil-900 px-3 py-2 font-mono text-base text-soil-50" />
        </label>

        {delta !== null && !Number.isNaN(delta) && (
          <p className="mt-3 font-mono text-sm text-soil-300">
            difference <span className={Math.abs(delta) <= 5 ? 'text-leaf-500' : 'text-alert-500'}>
              {delta > 0 ? '+' : ''}{delta.toFixed(1)} mm</span>
          </p>
        )}
        {err && <p className="mt-3 text-sm text-alert-500">{err}</p>}

        <div className="mt-5 flex gap-2">
          <button onClick={save} disabled={saving}
            className="flex-1 rounded bg-seed-500 px-4 py-2 text-sm font-semibold text-soil-900
                       hover:bg-seed-400 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button onClick={onClose}
            className="rounded border border-soil-800 px-4 py-2 text-sm text-soil-300 hover:bg-soil-800/50">
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
