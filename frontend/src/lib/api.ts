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
  sensor_reachable?: boolean;
}

export type Validation = {
  rows: { plant_tag: string; caliper_mm: number; ours_mm: number | null; frame_idx: number | null }[]
  stats: { n: number; unmatched: number; mae_mm?: number; bias_mm?: number; max_abs_err_mm?: number }
}

export type SensorStatus = {
  ip: string
  ports: Record<string, boolean>
  reachable: boolean
  streaming: boolean
}

export type SensorConfig = {
  scan_mode: number
  scan_mode_is_surface: boolean
  intensity_enabled: boolean
  generation_type?: number
  is_fixed_length?: boolean
  fixed_length_mm?: number
  eth_source_surface?: number
  eth_source_intensity?: number
}

export type SystemInfo = {
  host: string; machine: string; python: string
  detector_conf: number
  model: string | null; model_task: string | null
  retired_models: string[]
  torch: string | null; ultralytics: string | null
  opencv: string | null; numpy: string | null
  cuda: boolean; gpu: string | null
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

  sensorStatus: () => req<SensorStatus>('/api/sensor/status'),
  sensorConfig: () => req<{ ip: string; config: SensorConfig }>('/api/sensor/config'),
  setSensorConfig: (patch: Partial<{ intensity_enabled: boolean; fixed_length_mm: number; scan_mode_surface: boolean }>) =>
    req<{ changed: string[]; before: SensorConfig; after: SensorConfig }>('/api/sensor/config', {
      method: 'POST', body: JSON.stringify(patch),
    }),
  systemInfo: () => req<SystemInfo>('/api/sensor/system'),
  setDetectorConf: (conf: number) =>
    req<{ detector_conf: number }>('/api/sensor/detector', { method: 'POST', body: JSON.stringify({ conf }) }),
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
