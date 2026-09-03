# Running a live session

**Status: live acquisition works end-to-end.** Sensor → GoSDK → recorder → detector → SQLite → dashboard, verified on hardware 2026-08-19 (sessions 15 and 16).

Dashboard: **http://192.168.1.3:8000**

## The one thing that will surprise you

The sensor is **time-triggered**, not encoder-triggered. It builds a surface by stacking one profile per trigger and *assumes* the object is moving. A stationary object therefore yields the same profile on every row, and the surface comes out as vertical stripes — a smear, not a picture of the object. No detector can find a disc in that; it's geometry, not a software gap.

**Something has to move during the scan** — the object under the laser, or the sensor over it.

At the current settings (~890 Hz, 600 mm surfaces) one surface takes about **3 seconds**, which is enough to sweep a head through the laser line by hand. Sweep steadily; speed only distorts the Y axis, and diameters are measured on X for exactly that reason (D3).

## Start a live session

From the dashboard, or:

```bash
curl -s -X POST http://192.168.1.3:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"mode":"live","source":"192.168.1.10","notes":"bench test"}'
```

A live session runs until stopped:

```bash
curl -s -X POST http://192.168.1.3:8000/api/sessions/<ID>/stop
```

Watch progress: the Live page updates per frame, or `curl -s http://192.168.1.3:8000/api/health`.

## What the session does to the sensor

`LiveSource` writes configuration before streaming, because without it the sensor
publishes nothing usable. Each change is logged in the session's `meta.json`:

| Setting | Forced to | Why |
|---|---|---|
| Scan mode | Surface | Profile mode emits no surface messages |
| Intensity acquisition | on | the detector keys entirely on intensity texture |
| Surface generation | Fixed length, 600 mm | **Continuous never finalises a surface** — the sensor runs but no frame is ever emitted |
| Ethernet sources | Surface + Surface Intensity | the output list is separate from scan mode |

Override the surface length with `GOCATOR_SURFACE_MM=200` in the service environment (shorter = faster frames, less sweep time).

## Recording

Every live frame is written to disk **before** detection (D5), at roughly 7 MB/frame compressed — session 15 recorded 251 MB for 33 frames. Any session can be re-run through a newer detector later via `mode: "session"`.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `ReceiveData failed: kStatus -993` | timeout. Check generation type isn't Continuous, and that Ethernet sources include Surface. |
| Frames arrive, 0 heads, overlay shows vertical stripes | nothing moved — see above |
| `AddSource(SURFACE_INTENSITY) kStatus -997` | intensity acquisition off; `LiveSource` enables it, but the flush must land before the source is added |
| `sensor state 10, running 0` after start | `GoSystem_EnableData(system, true)` missing — without it the data channel never opens even though the sensor runs |
| Session ends instantly with a GoSdkError | another client (web UI, Accelerator) may hold the sensor; close the browser's scan page |

## Rebuilding the SDK

```bash
cd ~/gosdk/GO_SDK/Platform/kApi && make -f kApi-Linux_Arm64.mk -j4
cd ~/gosdk/GO_SDK/Gocator      && make -f GoSdk-Linux_Arm64.mk -j4
```
`backend/app/gosdk.py` loads `~/gosdk/GO_SDK/lib/linux_arm64/` by default (`GOSDK_ROOT` / `GOSDK_LIBDIR` override).
