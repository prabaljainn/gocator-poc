# Decision Log

Short ADRs, newest last. Each entry: what we chose, why, and what would reopen it.

## D1 — Parse .rec directly instead of using the emulator (2026-08-19)
The Windows-only emulator/SDK route was the documented path; instead we reverse-engineered the frame layout ([rec-format.md](rec-format.md)) and read the file with numpy memmap. Zero external tooling, seconds to open 1.7 GB, works on any OS. Reopen if: LMI changes the recording container in a future firmware.

## D2 — Texture matched filter over brightness/shape detection (2026-08-19)
Three approaches failed first (Otsu brightness → fragmentation; contour + inscribed circle → C-ring breaks; convex hull → leaf merge). Chosen detector: local-σ texture map, then "largest circle ≥ 55 % full of texture" per location, NMS, 1 px radius refinement, gates on valid-data fraction and mean texture. 55/55 verified true positives on the Tobetsu recording. Reopen if: a crop/season where seed-disc texture is absent (very early buds) becomes a target.

## D3 — Diameter is anchored to the X axis only (2026-08-19)
The recording is time-triggered; Y distances assume constant rig speed. X is optically calibrated. All mm conversions use X spacing. Reopen if: an encoder is added to the rig (then Y becomes trustworthy and 2-axis measures are fine).

## D4 — v1 live system is a validation-campaign tool (2026-08-19)
Purpose: prove pipeline vs caliper ground truth in one field day. Operational features (trends, fleet, auth) deliberately out. Reopen after: the campaign produces an acceptable MAE.

## D5 — Approach A: single Python service + thin C shim (2026-08-19)
One FastAPI process on the DGX Spark; GoSDK lives behind a ~100-line C ring-buffer shim polled via ctypes. Chosen over a split C daemon (Approach B) for build speed; the `FrameSource` interface keeps A→B a process split, not a rewrite. Raw frame is written to disk **before** detection — a detector crash cannot lose field data. Reopen if: the rig goes operational and capture must survive service crashes.

## D6 — DGX Spark is the v1 edge box (2026-08-19)
Already owned, ARM64 Linux (GoSDK supported), field-portable with a battery station. Jetson Orin is the later operational target — same architecture, same build. GoSDK has no macOS build, so the MacBook is viewer/dev only.

## D7 — React + Vite frontend (2026-08-19)
User decision: the UI is the seed of the operational product, worth the toolchain. Tailwind for styling. Phone-first Live page, desktop-first Session review.

## D8 — Record full raw frames every session (2026-08-19)
zstd-compressed npz (~15–25 MB/frame, ~1–2 GB per pass). Any session is forever re-runnable through improved detectors; disk on the Spark makes this free. Sensor-side .rec recording may be armed as an independent backup during the campaign.

## D9 — Manual ground-truth matching (2026-08-19)
Tap a detected head in the UI, assign plant tag + caliper mm. No auto-matching in v1 — validation numbers must be unambiguous.

## D10 — No simulated frame source (2026-08-19)
Dropped the planned `FakeLiveSource` (session replayed on a real-time timer). Challenged by prabal: the sensor is on the bench, and `ReplaySource` already feeds *real* captured data through the identical recorder → detector → store → WS → UI path. A timer-paced fake would only add a class to maintain and would still not exercise the one thing it claims to de-risk — GoSDK acquisition. Backend development uses `ReplaySource`; acquisition is proven against the real sensor. Reopen if: CI ever needs deterministic timing-sensitive tests that recorded sessions can't provide.

## D11 — GoSDK via ctypes, not a C shim (2026-08-19)
`backend/app/gosdk.py` binds libGoSdk/libkApi directly with ctypes instead of the C ring-buffer shim the original design called for. The SDK is a plain C API, so a shim would add a build step and a second place for bugs while buying nothing — Python already copies each row out of SDK memory before the message is destroyed. Supersedes the shim in architecture.md. Reopen if: acquisition ever needs to outlive the Python process, or per-frame copy cost shows up in profiling.

## D12 — Detector takes pixel size as an argument (2026-08-19)
`preprocess()` / `find_heads()` accept `dx_mm`/`dy_mm`/`px_mm` rather than reading `rec_reader`'s constants. Live frames report their own resolution (0.1278mm X on the bench vs 0.124mm in the Tobetsu file — it moves with the sensor's active-area settings), so hardcoding the recording's value would silently mis-scale every live diameter by ~3%.

## D13 — Live capture requires relative motion (2026-08-19, physical constraint)
The sensor is time-triggered, so a stationary object produces an identical profile every row: the surface is a smear along Y, not a picture, and no detector can recover a disc from it. Confirmed on the bench — live frames arrived correctly but showed vertical stripes. Either the object or the sensor must move during a surface. Surface length is set to 600mm (~3s at ~890Hz) to leave time for a hand sweep. Diameters stay anchored to X (D3), which is unaffected by sweep-speed variation; Y is not trustworthy under a hand sweep.
