export type Head = {
  id: number; frame_id: number; frame_idx: number;
  cx_mm: number; cy_mm: number; dia_mm: number;
  tex_in: number; valid_frac: number; height_mm: number;
  truncated: number; accepted: number;
}

export type Session = {
  id: number; started_at: string; ended_at: string | null;
  mode: string; source: string; dir: string; notes: string;
  state: string; frame_count: number; head_count: number;
}

export type Health = {
  running: boolean; session_id: number | null;
  paused?: boolean; fps?: number;
  frames_done: number; heads_found: number;
  source: { kind: string; connected: boolean; frames_seen: number; detail: string } | null;
  disk_free_gb: number; sensor_ip: string; live_acquisition: boolean;
}

export type Validation = {
  rows: { plant_tag: string; caliper_mm: number; ours_mm: number | null; frame_idx: number | null }[]
  stats: { n: number; unmatched: number; mae_mm?: number; bias_mm?: number; max_abs_err_mm?: number }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`)
  return r.json()
}

export const api = {
  health: () => req<Health>('/api/health'),
  sessions: () => req<Session[]>('/api/sessions'),
  session: (id: number) => req<Session & { heads: Head[] }>(`/api/sessions/${id}`),
  heads: (id: number) => req<Head[]>(`/api/sessions/${id}/heads`),
  validation: (id: number) => req<Validation>(`/api/sessions/${id}/validation`),
  start: (body: { mode: string; source: string; notes?: string; limit?: number | null; fps?: number }) =>
    req<{ session_id: number; dir: string }>('/api/sessions', {
      method: 'POST', body: JSON.stringify(body),
    }),
  stop: (id: number) => req<{ stopping: boolean }>(`/api/sessions/${id}/stop`, { method: 'POST' }),
  pause: (id: number) => req<{ paused: boolean }>(`/api/sessions/${id}/pause`, { method: 'POST' }),
  resume: (id: number) => req<{ resumed: boolean }>(`/api/sessions/${id}/resume`, { method: 'POST' }),
  step: (id: number) => req<{ stepped: boolean }>(`/api/sessions/${id}/step`, { method: 'POST' }),
  setSpeed: (id: number, fps: number) =>
    req<{ fps: number }>(`/api/sessions/${id}/speed`, { method: 'POST', body: JSON.stringify({ fps }) }),
  addGroundTruth: (b: { session_id: number; plant_tag: string; caliper_mm: number; head_id: number | null }) =>
    req<{ id: number }>('/api/ground-truth', { method: 'POST', body: JSON.stringify(b) }),
  overlayUrl: (sid: number, frameIdx: number) => `/api/sessions/${sid}/overlay/${frameIdx}.jpg`,
}
