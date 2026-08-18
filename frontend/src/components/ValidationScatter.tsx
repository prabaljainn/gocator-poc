import type { Validation } from '../lib/api'

/** Pipeline vs caliper. Points on the diagonal are perfect agreement;
 *  the band shows ±5 mm. Hand-drawn SVG — no chart library for one plot. */
export function ValidationScatter({ rows }: { rows: Validation['rows'] }) {
  const pts = rows.filter((r) => r.ours_mm !== null) as { plant_tag: string; caliper_mm: number; ours_mm: number }[]
  if (!pts.length) return null

  const vals = pts.flatMap((p) => [p.caliper_mm, p.ours_mm])
  const pad = 8
  const lo = Math.floor((Math.min(...vals) - pad) / 10) * 10
  const hi = Math.ceil((Math.max(...vals) + pad) / 10) * 10
  const W = 360, H = 360, M = 44
  const sx = (v: number) => M + ((v - lo) / (hi - lo)) * (W - M - 12)
  const sy = (v: number) => H - M - ((v - lo) / (hi - lo)) * (H - M - 12)
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4)
  const band = Math.abs(sy(lo) - sy(lo + 5))

  return (
    <figure className="rounded-lg border border-soil-800 bg-soil-900/60 p-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
        aria-label="Scatter of pipeline diameter against caliper diameter, with a plus or minus 5 millimetre agreement band around the diagonal.">
        <g stroke="currentColor" className="text-soil-800" strokeWidth="1">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={sx(t)} y1={sy(lo)} x2={sx(t)} y2={sy(hi)} />
              <line x1={sx(lo)} y1={sy(t)} x2={sx(hi)} y2={sy(t)} />
            </g>
          ))}
        </g>
        <polygon points={`${sx(lo)},${sy(lo) - band} ${sx(hi)},${sy(hi) - band} ${sx(hi)},${sy(hi) + band} ${sx(lo)},${sy(lo) + band}`}
          className="fill-leaf-500/10" />
        <line x1={sx(lo)} y1={sy(lo)} x2={sx(hi)} y2={sy(hi)} className="stroke-soil-300" strokeWidth="1" strokeDasharray="4 4" />
        {pts.map((p, i) => (
          <g key={i}>
            <circle cx={sx(p.caliper_mm)} cy={sy(p.ours_mm)} r="5"
              className={Math.abs(p.ours_mm - p.caliper_mm) <= 5 ? 'fill-leaf-500' : 'fill-alert-500'} />
            <title>{`${p.plant_tag}: caliper ${p.caliper_mm} mm, ours ${p.ours_mm.toFixed(1)} mm`}</title>
          </g>
        ))}
        <g className="fill-soil-300 font-mono" fontSize="10">
          {ticks.map((t) => (
            <g key={t}>
              <text x={sx(t)} y={H - M + 16} textAnchor="middle">{t}</text>
              <text x={M - 8} y={sy(t) + 3} textAnchor="end">{t}</text>
            </g>
          ))}
          <text x={(sx(lo) + sx(hi)) / 2} y={H - 6} textAnchor="middle" fontSize="11">caliper (mm)</text>
          <text x={12} y={(sy(lo) + sy(hi)) / 2} textAnchor="middle" fontSize="11"
            transform={`rotate(-90 12 ${(sy(lo) + sy(hi)) / 2})`}>pipeline (mm)</text>
        </g>
      </svg>
      <figcaption className="mt-1 text-center text-xs text-soil-300">
        {pts.length} paired measurement{pts.length === 1 ? '' : 's'} · shaded band is ±5 mm
      </figcaption>
    </figure>
  )
}
