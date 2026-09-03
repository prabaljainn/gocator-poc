import { useEffect, useState, useRef, useCallback } from 'react'

interface Box {
  id: string
  xc: number
  yc: number
  w: number
  h: number
  label: string
}

interface SourceInfo {
  name: string
  stem: string
  total_frames: number
  verified_frames: number
}

interface FrameData {
  source: string
  frame_idx: number
  total_frames: number
  verified: boolean
  boxes: Box[]
  width: number
  height: number
  image_url: string
}

export function Annotate() {
  const [sources, setSources] = useState<SourceInfo[]>([])
  const [selectedSource, setSelectedSource] = useState<string>('')
  const [frameIdx, setFrameIdx] = useState<number>(0)
  const [frameData, setFrameData] = useState<FrameData | null>(null)
  const [boxes, setBoxes] = useState<Box[]>([])
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null)
  const [isDrawing, setIsDrawing] = useState<boolean>(false)
  const [drawStart, setDrawStart] = useState<{ x: number; y: number } | null>(null)
  const [currentDraw, setCurrentDraw] = useState<{ xc: number; yc: number; w: number; h: number } | null>(null)
  const [saving, setSaving] = useState<boolean>(false)
  const [saveStatus, setSaveStatus] = useState<string>('')

  const containerRef = useRef<HTMLDivElement>(null)

  // 1. Fetch available sources
  useEffect(() => {
    fetch('/api/annotate/sources')
      .then(res => res.json())
      .then((data: SourceInfo[]) => {
        setSources(data)
        if (data.length > 0 && !selectedSource) {
          setSelectedSource(data[0].name)
        }
      })
      .catch(console.error)
  }, [])

  // 2. Fetch frame annotation data
  const loadFrame = useCallback((source: string, idx: number) => {
    if (!source) return
    setSelectedBoxId(null)
    setSaveStatus('')
    fetch(`/api/annotate/frame/${encodeURIComponent(source)}/${idx}`)
      .then(res => res.json())
      .then((data: FrameData) => {
        setFrameData(data)
        setBoxes(data.boxes || [])
      })
      .catch(console.error)
  }, [])

  useEffect(() => {
    if (selectedSource) {
      loadFrame(selectedSource, frameIdx)
    }
  }, [selectedSource, frameIdx, loadFrame])

  // Save current frame
  const saveFrame = useCallback(async (andNext = false) => {
    if (!selectedSource || !frameData) return
    setSaving(true)
    try {
      const res = await fetch(`/api/annotate/frame/${encodeURIComponent(selectedSource)}/${frameIdx}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ boxes, verified: true })
      })
      const out = await res.json()
      setSaveStatus(`Saved (${out.box_count} heads)`)
      setFrameData(prev => prev ? { ...prev, verified: true } : null)

      // Refresh sources to update progress counts
      fetch('/api/annotate/sources')
        .then(r => r.json())
        .then(setSources)
        .catch(() => null)

      if (andNext && frameIdx < (frameData.total_frames - 1)) {
        setFrameIdx(prev => prev + 1)
      }
    } catch (e) {
      setSaveStatus('Error saving')
    } finally {
      setSaving(false)
    }
  }, [selectedSource, frameIdx, frameData, boxes])

  // Keyboard navigation shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger shortcuts if focus is in an input
      if (['INPUT', 'SELECT'].includes((e.target as HTMLElement).tagName)) return

      if (e.key === ' ' || e.key === 'd' || e.key === 'D') {
        e.preventDefault()
        saveFrame(true)
      } else if (e.key === 'a' || e.key === 'A') {
        e.preventDefault()
        if (frameIdx > 0) setFrameIdx(prev => prev - 1)
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedBoxId) {
          e.preventDefault()
          deleteBox(selectedBoxId)
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [saveFrame, frameIdx, selectedBoxId])

  // Box deletion
  const deleteBox = (id: string) => {
    setBoxes(prev => prev.filter(b => b.id !== id))
    if (selectedBoxId === id) setSelectedBoxId(null)
  }

  // Mouse interaction on image canvas
  const getNormCoords = (e: React.MouseEvent) => {
    if (!containerRef.current) return { x: 0, y: 0 }
    const rect = containerRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    return { x, y }
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.box-control')) return
    const { x, y } = getNormCoords(e)
    setIsDrawing(true)
    setDrawStart({ x, y })
    setCurrentDraw(null)
    setSelectedBoxId(null)
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDrawing || !drawStart) return
    const { x, y } = getNormCoords(e)
    const xc = (drawStart.x + x) / 2
    const yc = (drawStart.y + y) / 2
    const w = Math.abs(x - drawStart.x)
    const h = Math.abs(y - drawStart.y)
    setCurrentDraw({ xc, yc, w, h })
  }

  const handleMouseUp = () => {
    if (isDrawing && currentDraw && currentDraw.w > 0.01 && currentDraw.h > 0.01) {
      const newBox: Box = {
        id: `box_${Date.now()}`,
        xc: currentDraw.xc,
        yc: currentDraw.yc,
        w: currentDraw.w,
        h: currentDraw.h,
        label: 'sunflower_head'
      }
      setBoxes(prev => [...prev, newBox])
      setSelectedBoxId(newBox.id)
    }
    setIsDrawing(false)
    setDrawStart(null)
    setCurrentDraw(null)
  }

  const totalVerified = sources.reduce((acc, s) => acc + s.verified_frames, 0)
  const totalFramesAll = sources.reduce((acc, s) => acc + s.total_frames, 0)

  return (
    <div className="flex flex-col gap-4">
      {/* Top Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-soil-800 bg-soil-900/60 p-3">
        <div className="flex items-center gap-3">
          <label className="text-xs font-semibold uppercase tracking-wider text-soil-400">Dataset Source:</label>
          <select
            value={selectedSource}
            onChange={e => { setSelectedSource(e.target.value); setFrameIdx(0); }}
            className="rounded border border-soil-700 bg-soil-800 px-2.5 py-1 text-sm text-soil-100 focus:outline-none focus:ring-1 focus:ring-seed-400"
          >
            {sources.map(s => (
              <option key={s.name} value={s.name}>
                {s.stem} ({s.verified_frames}/{s.total_frames} verified)
              </option>
            ))}
          </select>

          <div className="h-4 w-px bg-soil-700" />

          {/* Frame Navigation */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setFrameIdx(prev => Math.max(0, prev - 1))}
              disabled={frameIdx === 0}
              className="rounded bg-soil-800 px-2.5 py-1 text-sm font-medium text-soil-200 hover:bg-soil-700 disabled:opacity-40"
              title="Shortcut: A"
            >
              ← Prev (A)
            </button>
            <span className="px-2 font-mono text-sm text-soil-100">
              Frame <strong className="text-seed-400">{frameIdx + 1}</strong> of {frameData?.total_frames || 0}
            </span>
            <button
              onClick={() => setFrameIdx(prev => Math.min((frameData?.total_frames || 1) - 1, prev + 1))}
              disabled={frameIdx >= (frameData?.total_frames || 1) - 1}
              className="rounded bg-soil-800 px-2.5 py-1 text-sm font-medium text-soil-200 hover:bg-soil-700 disabled:opacity-40"
              title="Shortcut: D or Space"
            >
              Next (D) →
            </button>
          </div>
        </div>

        {/* Status & Actions */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-soil-400">Overall Curation:</span>
            <span className="rounded bg-soil-800 px-2 py-0.5 text-xs font-semibold text-seed-400">
              {totalVerified} / {totalFramesAll} frames
            </span>
          </div>

          <div className="h-4 w-px bg-soil-700" />

          <button
            onClick={() => setBoxes([])}
            className="rounded border border-red-500/30 px-2.5 py-1 text-xs text-red-400 hover:bg-red-500/10"
          >
            Clear All
          </button>

          <button
            onClick={() => saveFrame(true)}
            disabled={saving}
            className="flex items-center gap-1.5 rounded bg-seed-500 px-3 py-1 text-sm font-semibold text-soil-900 shadow hover:bg-seed-400 disabled:opacity-50"
          >
            ✓ Save & Next (Space)
          </button>
        </div>
      </div>

      {/* Main Annotation Workspace */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        {/* Viewport */}
        <div className="lg:col-span-3 rounded-lg border border-soil-800 bg-soil-950 p-2 flex flex-col items-center justify-center min-h-[600px] overflow-hidden">
          {frameData ? (
            <div
              ref={containerRef}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              className="relative select-none cursor-crosshair border border-soil-800 max-h-[750px]"
              style={{
                aspectRatio: `${frameData.width} / ${frameData.height}`,
                width: '100%',
                maxWidth: '680px',
              }}
            >
              <img
                src={frameData.image_url}
                alt="Frame"
                className="h-full w-full object-contain pointer-events-none"
              />

              {/* Overlaid Annotation Boxes */}
              {boxes.map((b, i) => {
                const left = `${(b.xc - b.w / 2) * 100}%`
                const top = `${(b.yc - b.h / 2) * 100}%`
                const width = `${b.w * 100}%`
                const height = `${b.h * 100}%`
                const isSelected = selectedBoxId === b.id

                return (
                  <div
                    key={b.id}
                    onClick={(e) => { e.stopPropagation(); setSelectedBoxId(b.id); }}
                    style={{ left, top, width, height }}
                    className={`absolute box-control border-2 transition-colors ${
                      isSelected ? 'border-yellow-400 bg-yellow-400/20' : 'border-green-400 bg-green-400/15'
                    }`}
                  >
                    {/* Top Label & Delete Button */}
                    <div className="absolute -top-6 left-0 flex items-center gap-1 bg-soil-900/90 px-1.5 py-0.5 rounded text-[10px] font-mono text-soil-100 shadow border border-soil-700">
                      <span>Head #{i + 1}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); deleteBox(b.id); }}
                        className="ml-1 text-red-400 hover:text-red-200 font-bold px-0.5"
                        title="Delete box (e.g. false rail/leaf)"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                )
              })}

              {/* Drawing Preview */}
              {isDrawing && currentDraw && (
                <div
                  style={{
                    left: `${(currentDraw.xc - currentDraw.w / 2) * 100}%`,
                    top: `${(currentDraw.yc - currentDraw.h / 2) * 100}%`,
                    width: `${currentDraw.w * 100}%`,
                    height: `${currentDraw.h * 100}%`,
                  }}
                  className="absolute border-2 border-dashed border-yellow-300 bg-yellow-400/20 pointer-events-none"
                />
              )}
            </div>
          ) : (
            <div className="text-sm text-soil-500">Loading frame...</div>
          )}
        </div>

        {/* Sidebar Controls & Checklist */}
        <div className="flex flex-col gap-4 rounded-lg border border-soil-800 bg-soil-900/50 p-4">
          <div>
            <h3 className="text-sm font-semibold text-soil-100">Annotation Guidelines</h3>
            <ul className="mt-2 space-y-1.5 text-xs text-soil-300">
              <li>• Click <span className="font-bold text-red-400">×</span> on false detections (clamps, rails, leaves) to delete them.</li>
              <li>• Click & drag anywhere on the image to add missed flower heads.</li>
              <li>• Tighten boxes around the <strong className="text-seed-400">central seed disc</strong> only (exclude floppy ray petals).</li>
              <li>• Press <kbd className="rounded bg-soil-800 px-1 py-0.5 font-mono text-soil-200">Space</kbd> or <kbd className="rounded bg-soil-800 px-1 py-0.5 font-mono text-soil-200">D</kbd> to save and advance.</li>
            </ul>
          </div>

          <div className="h-px bg-soil-800" />

          {/* Current Frame Info */}
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-soil-400">Current Frame Heads:</span>
              <span className="font-mono text-sm font-bold text-seed-400">{boxes.length}</span>
            </div>
            {saveStatus && (
              <div className="mt-2 rounded bg-green-500/10 border border-green-500/30 p-2 text-center text-xs font-semibold text-green-400">
                {saveStatus}
              </div>
            )}
          </div>

          <div className="mt-auto pt-4 border-t border-soil-800">
            <div className="text-xs text-soil-400 mb-2">Shortcut Cheatsheet:</div>
            <div className="grid grid-cols-2 gap-1 text-[11px] font-mono text-soil-300">
              <div><kbd className="bg-soil-800 px-1 rounded">Space/D</kbd> Save+Next</div>
              <div><kbd className="bg-soil-800 px-1 rounded">A</kbd> Prev Frame</div>
              <div><kbd className="bg-soil-800 px-1 rounded">Del/Bksp</kbd> Delete Box</div>
              <div><kbd className="bg-soil-800 px-1 rounded">Drag</kbd> Add New</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
