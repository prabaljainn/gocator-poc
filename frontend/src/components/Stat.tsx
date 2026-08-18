export function Stat({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className="rounded-lg border border-soil-800 bg-soil-900/60 px-4 py-3">
      <div className={`font-mono text-2xl font-semibold tabular-nums ${accent ? 'text-seed-400' : 'text-soil-50'}`}>
        {value}
      </div>
      <div className="mt-0.5 text-xs tracking-wider text-soil-300 uppercase">{label}</div>
    </div>
  )
}
