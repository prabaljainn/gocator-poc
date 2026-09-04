# Jetson AGX Orin bring-up (norl-jetson1)

The POC runs **entirely on the Jetson**, in a container, off the NVMe. Verified 2026-09-05.

Dashboard: **http://192.168.23.101:8000**

## The box

| | |
|---|---|
| Host | `norl-jetson1`, `ssh jetson-lab-local` (user `norl`, passwordless sudo) |
| Hardware | Jetson AGX Orin Dev Kit, 8 cores, 61 GB RAM |
| JetPack | 5.1.2 (L4T r35.4.1) / Ubuntu 20.04 / **Python 3.8** |
| Repo + data | `/data/gocator-poc` on a 3.7 TB NVMe (3.3 TB free) — **not** the 57 GB eMMC |
| Net | `eth0` 192.168.23.101/24, no default route, no DNS |

**This box runs production.** `tokyubus-mediamtx`, `tokyubus-web-ui`, `tokyubus-mosquitto`
are live, and `/data/norl-release` holds 110 GB of tokyubus artifacts. Everything here is
confined to `/data/gocator-poc` and one container. No host packages were installed.

## Why a container

CUDA/cuDNN/TensorRT are **not** installed on the host, and JetPack 5.1.2 pins Python 3.8 —
the only Python NVIDIA ships a CUDA torch for on this L4T. The existing
`norlinc/tokyubus2026:ai-detector-jetson-v1.0.0` image already carries a working aarch64
stack for this exact board: torch 2.0.0+nv23.05 (CUDA on Orin), torchvision, ultralytics
8.3.0, TensorRT 8.5.2.2, OpenCV 4.13. `deploy/Dockerfile` adds only FastAPI/uvicorn on top.

`eval_type_backport` is in that image so Pydantic can evaluate the repo's `int | None`
annotations on 3.8. **The repo itself is unmodified** — the 3.8 shim lives in the image,
where the constraint lives, not in code the Spark and Mac also run.

## Run

```bash
ssh jetson-lab-local
docker start gocator-poc                 # already set --restart unless-stopped
docker logs -f gocator-poc
curl -s localhost:8000/api/health
```

Rebuild after a code change (needs the proxy below for pip only):

```bash
cd /data/gocator-poc && docker build --network=host -t gocator-poc:jetson -f deploy/Dockerfile .
```

Code is bind-mounted from `/data/gocator-poc`, so a plain `docker restart gocator-poc`
picks up edits — a rebuild is only needed when dependencies change.

Checks, both of which pass on the Jetson:

```bash
docker exec -w /work gocator-poc python3 detect.py --selftest
docker exec -w /work gocator-poc python3 -m backend.tests.test_pipeline
```

## Verified on hardware

- `detect.py --selftest` → 203.4 mm vs 200.0 mm (1.7%), passes on py3.8.
- GPU inference **~75 ms/frame** steady state (first frame ~6 s is CUDA warm-up).
- Replay writes raw `.npz` to disk before detection (invariant 1 holds).
- `backend.tests.test_pipeline` — all 6 pass, same as Mac and Spark.
- Golden replay: 42 frames -> **65 detections, 62 accepted** (3 rejected for
  `valid_frac` below 0.70), byte-for-byte the same decisions as the Spark.
- Every API route returns 200; all four SPA pages and their assets load.
- Both recordings staged, so the Dataset Lab sees all 75 curated frames
  (37 from Tobetsu, 38 from 3sept).

Three `dict | dict` merges (`main.py`, `store.py`, `gosdk.py`) were Python 3.9+ only and
had to become `{**a, **b}` / `.update()`. Two of them had never fired: `store.py` breaks
the validation endpoint as soon as ground truth exists, and `gosdk.py` breaks the moment
the sensor comes back. Those are repo fixes, not Jetson-local ones — both other machines
got them too.

## Two things that will bite you

**1. No internet, and no DNS.** There is no default route on 192.168.23.0/24. Nothing
installs until you tunnel out through a machine that has internet:

```bash
# on the Mac
python3 tools/offline_proxy.py 3128 &                       # stdlib HTTP/CONNECT proxy
ssh -f -N -R 3128:127.0.0.1:3128 jetson-lab-local        # expose it on the Jetson
# on the Jetson
export http_proxy=http://127.0.0.1:3128 https_proxy=http://127.0.0.1:3128
```

`docker build --network=host` is what lets pip inside a build reach that forward.
The tunnel is only needed to install things; the POC runs fine without it.

**2. The clock has no NTP** (UDP 123 does not cross the HTTP proxy), so it drifts and
was found ~2 days behind, which also makes apt reject release files as "not valid yet".
It was set by hand on 2026-09-05 and the tokyubus containers rode through the jump fine.
Re-sync it from a machine with a good clock whenever it drifts:

```bash
ssh jetson-lab-local "sudo date -u -s '$(date -u '+%Y-%m-%d %H:%M:%S')'"
```

Check it before trusting any session timestamp — sessions recorded while it was wrong are
stamped two days early.

## Sensor access — not available yet

`eth0` carries a second address, `192.168.1.20/24`, added non-persistently:

```bash
sudo ip addr add 192.168.1.20/24 dev eth0     # reverts on reboot
```

From there the **Spark (192.168.1.3) is reachable**, so the Jetson is on the right segment.
The **Gocator at 192.168.1.10 is not** — no ARP reply, so it is powered off or unplugged,
not misrouted. Until it is back, the Jetson is replay-only. `gosdk.py` needs no compiled
shim (pure ctypes, already defaults to `linux_arm64`), so live acquisition should be a
matter of dropping the SDK's aarch64 `.so` files in and pointing `GOSDK_ROOT` at them.

Do not use 192.168.1.7 — that is the Mac's documented alias.

Note that `/api/health` still reports `sensor_ip: 192.168.1.10` and
`live_acquisition: true` on this box. That flag reflects config, not reachability —
the UI will offer a live mode here that cannot work until the sensor is back.

## Models

All six weight files live in `data/models/`, same as everywhere else — nothing is moved
aside or renamed per machine. `get_detector()` walks the candidate list and the first one
that *actually infers* wins, so the Jetson sorts itself out at runtime:

```
ml_detector: using sunflower_curated_yolov8n.onnx
ml_detector: sunflower_curated_yolov8n.onnx failed at inference
             (ModuleNotFoundError: No module named 'onnxruntime'); retiring it
ml_detector: using sunflower_curated_yolov8n.pt
```

That costs one wasted frame on startup and is logged. Validating up front with a synthetic
probe was tried first and rejected: any predict before the real ones left the Spark's ONNX
path ~8x slower (4 ms -> 35 ms) for the life of the process, and a fresh model instance did
not clear it.

So on the Jetson inference runs through torch/CUDA on the `.pt` at ~73 ms/frame. Installing
`onnxruntime` here would only change which branch wins; the PyPI `onnxruntime-gpu` wheel is
x86-only, so it would land on CPU.

## Making it faster

Only worth doing if ~10 fps end-to-end turns out not to be enough — for a laser profiler it
probably is. Two levers, in order:

1. **TensorRT.** Would attack the 68 ms inference. **Do not export the engine on the
   Jetson**: `model.fuse()` there writes 896 NaNs into `model.3.conv.weight` and the forward
   pass goes non-finite (ultralytics 8.3.0 + torch 2.0.0+nv on Orin; the Spark fuses the same
   file cleanly, and the normal predict path is unaffected). Export on the Spark, ship the
   `.engine`, and validate it against the 65-head golden replay before trusting it.
2. **Preprocess is 31 ms of the ~101 ms budget and is pure CPU** (downsample, resize,
   median blur). Once inference shrinks, this dominates.

## Live acquisition

The GoSDK aarch64 libraries are staged at `/data/gocator-poc/gosdk/GO_SDK/lib/linux_arm64/`
(copied from the Spark — it is aarch64 too, so the same build works). The container runs
with `GOSDK_ROOT=/work/gosdk/GO_SDK`, and `gosdk.py` needs no compiled shim: it is pure
ctypes and already defaults to the `linux_arm64` libdir.

Verified without the sensor: `libkApi.so` and `libGoSdk.so` both load and **all 42 symbol
signatures bind** inside the running service. That is as far as it can be checked until the
Gocator is back on the network.

### The Jetson is comfortably fast enough for live

Measured, not assumed:

| | |
|---|---|
| sensor emits a surface every | **3.49 s** (kStamp µs at +16; 143.1 s across 42 surfaces, and 3389 rows at the 994 Hz trigger) |
| Jetson full service pipeline | **0.74 s/frame** |
| headroom | **4.7x** |

So no pipeline optimisation was done, deliberately. For the record, where that 0.74 s goes:

| stage | ms | share |
|---|---|---|
| `save_raw` (`np.savez_compressed`) | 661 | **86%** |
| YOLO inference | 69 | 9% |
| preprocess | 31 | 4% |
| overlay jpg | 10 | 1% |
| read .rec | 0.4 | — |

Compression dominates and is still only 18% of the sensor's 3.49 s budget. Alternatives were
benchmarked in case it ever matters — uncompressed `savez` is 110 ms but 41 MB/frame instead
of 6.3 MB; deflate level 1 is 370 ms for the same size. Neither is worth doing today.

### Live acquisition works — verified on hardware 2026-09-05

First real streaming run. Lens was covered, so every surface came back 0% valid Z, which
still exercises the whole path.

**The container must run `--network=host`.** GoSDK discovers the sensor by UDP broadcast, and
on Docker's bridge network `GoSystem_FindSensorByIpAddress` fails with `kStatus -999` even
though TCP to 3190/3192 works fine. Host networking is not optional for live.

`eth0` also needs the sensor-subnet alias, and it is **not persistent** — it disappeared once
without a reboot:

```bash
sudo ip addr add 192.168.1.20/24 dev eth0     # re-add after any drop
```

**Live geometry differs from the recording**, which is why `preprocess` takes spacing as
arguments:

| | recording | live sensor |
|---|---|---|
| surface | 3389 x 4033 | **3367 x 6390** (1.6x the pixels) |
| x spacing | 0.1240 mm | **0.1278 mm** |
| working px | 0.4961 mm | **0.5112 mm** |
| interval between surfaces | 3.49 s | **~2.4 s** |

**Budget, measured on live frames with the lens open** (41.9% valid Z):

| stage | covered lens | **real data** |
|---|---|---|
| `save_raw` | 623 ms | **1497 ms** (npz 12.8 MB, not 0.1 MB) |
| preprocess | 36 ms | 38 ms |
| overlay | 12 ms | 13 ms |
| **steady-state total** | 0.69 s | **1.61 s** |
| sensor interval | 2.4 s | **4.35 s** |
| **headroom** | ~3x | **~2.7x** |

Compression dominates and grows with real data, as expected — an all-invalid frame barely
compresses. 2.7x is comfortable, but it is the number to re-check if the surface size or
trigger rate changes.

### Two bugs this found, both fixed

Neither was reachable without hardware:

1. **`limit` was ignored for live sessions.** `ReplaySource` honoured it; `LiveSource` never
   received it, and a live stream never ends on its own — a session asked for 3 surfaces ran
   to 45 before being stopped by hand.
2. **`meta.json` recorded `rec_reader`'s Tobetsu constants for live sessions**
   (`x_spacing_mm` 0.1240 instead of the sensor's 0.1278). Detection used the right values —
   they flow through `frame.dx_mm` — but anything re-derived from the recorded metadata would
   be 3% out, and invariant 2 converts diameters via X spacing.

### Sensor drop and recovery — tested by partitioning the sensor

Simulated with `sudo ip route add blackhole 192.168.1.10/32`, which is what a cable pull looks
like to the software and leaves the rest of the box untouched.

- **Before:** the drop surfaced as `GoSystem_ReceiveData failed: kStatus -993`, the session
  ended in `error`, and restoring the link did nothing. Frames captured before the cut were
  all safely on disk — D5 held.
- **Now:** `LiveSource` reconnects. Health shows
  `connected=false … reconnecting (attempt N): <error>` while it retries, then resumes.
  Verified across a real cut: 28 frames, indices 0-27 contiguous, no duplicates, none
  overwritten. The frame counter deliberately survives a reconnect — restarting at 0 would
  overwrite the session's own recorded frames.
- Retries are unbounded by default (a sensor reboot should not end a field pass) but back off
  in interruptible slices, so **stop works while disconnected** — measured at 2-3 s.
- A stop that lands mid-reconnect now records `stopped`, not `error`. It recorded `error`
  until this was tested: the retry path re-raised on the stop flag.
- **`fps` no longer paces live sessions.** The sensor sets the rate; sleeping would only back
  frames up in the SDK buffer. Verified: 4 surfaces at `fps=0.2` took 15 s (sensor-limited),
  not the 20 s+ the pacing would have imposed.
- **`/api/health` now carries `sensor_reachable`** — a cached TCP probe — alongside
  `live_acquisition`, which was always a capability check (can the SDK load) rather than a
  statement about the device being there. Verified flipping false and back across a cut.

### The sensor's configuration was changed

`GocatorStream.open()` writes settings and `close()` does not restore them. Pre-change state
is saved in `data/sensor-config-snapshot.json`:

| setting | was | now |
|---|---|---|
| intensity_enabled | False | **True** |
| fixed_length_mm | 1000.0 | **600.0** |
| eth source: surface intensity | absent | **added** |

scan mode was already Surface and generation already fixed-length, so those were untouched.
These three are what the pipeline requires — restoring them turns live acquisition off again.


## Control tab

`/control` in the dashboard, backed by `backend/app/sensor.py`:

- **Sensor** — IP, per-port reachability (control/upgrade/data/web), whether a session holds
  the connection. Polls every 5 s and needs no SDK connection, so it is safe while streaming.
- **This machine** — which model actually loaded, its task, GPU, torch/ultralytics/OpenCV/numpy
  versions, and any candidate that was *retired* at first inference. The Jetson shows
  `retired: sunflower_curated_yolov8n.onnx`, which makes the self-healing selection visible
  rather than buried in a log.
- **Sensor configuration** — reads live over GoSDK (~1.5 s, so it is on a button, not on load)
  and writes back `intensity_enabled` and `fixed_length_mm`. Writes are confirmed in the UI
  first, range-checked server-side (10-5000 mm), and reported as a before/after diff.
- **Detector tuning** — detection confidence, applied to the next frame. Not persisted across
  a restart, which is deliberate: it is a knob for looking at data, not a config setting.

**Only one SDK connection at a time.** Every config read and write returns 409 while a session
is streaming. This is not theoretical — it fired during testing when a live session was started
from the dashboard while config writes were being exercised from the shell.

Verified against the device: a 600 -> 620 mm write was applied, confirmed by an independent
re-read, and restored to 600.
