# gocator-poc — agent guide

Sunflower head detection + diameter measurement from a Gocator 2690 laser profiler. Field data from Tobetsu, Hokkaidō. Owner: prabal.

## Read these before coding

- `docs/architecture.md` — the approved live-system design (Approach A). Follow it; deviations go through `docs/decisions.md`.
- `docs/rec-format.md` — the reverse-engineered .rec format. Do not re-derive it.
- `docs/decisions.md` — ADR log. **Add an entry for every non-obvious choice; check it before proposing alternatives — several tempting approaches are documented failures (D2).**

## Map

| Path | What |
|---|---|
| `rec_reader.py` | .rec parser (42-frame Tobetsu file). Standalone, numpy-only. |
| `detect.py` | Detection core + `--selftest`. Shared by offline and live paths. Keep it importable and dependency-light — the live service wraps it, never forks it. |
| `backend/` | FastAPI live service (per architecture.md) — acquisition shim, recorder, store, API/WS. |
| `frontend/` | React + Vite + Tailwind UI. |
| `out/` | Generated artifacts (gitignored): overlays, `review.png` contact sheet, `detections.csv`. |
| `tobetsu-data-*.rec` | 1.7 GB field recording (gitignored). Ask prabal if missing. |

## Commands

```bash
.venv/bin/python detect.py --selftest              # must pass before any detector change lands
.venv/bin/python detect.py tobetsu-data-20260730-1416.rec        # full run → out/
.venv/bin/python detect.py tobetsu-data-20260730-1416.rec 10 11  # specific frames
.venv/bin/python rec_reader.py <file.rec>          # reader sanity check
```

Python via `.venv` (numpy, scipy, opencv-python-headless, pillow). Homebrew python3 is PEP-668 locked — never pip-install globally.

## Invariants (violating these = bug)

1. **Raw frame hits disk before detection** in any live path (architecture.md, D5).
2. **Diameters convert via X spacing only** (0.124 mm/px raw; Y is time-triggered and untrusted — D3).
3. `.rec` Z rasters are **big-endian** int16; header fields are little-endian. Ring-banding artifacts = wrong byte order.
4. `0x8000` is invalid-Z, not data.
5. Detector changes must keep `--selftest` passing and should be verified on the golden replay (55 heads on the Tobetsu file; eyeball `out/review.png`).

## Gotchas that already cost time

- `cv2.threshold(...THRESH_OTSU)` returns the *lower class edge*; compare strictly `>`.
- `cv2.filter2D` default border reflection fabricates texture at image edges — use `BORDER_CONSTANT`.
- GoSDK has **no macOS build** (Linux x64/ARM64, Windows). MacBook is viewer/dev only; live acquisition runs on the DGX Spark (v1) or Jetson (later).
- `numpy.argmax` tie-breaks to the first (top-left) element — never use it alone to localize a plateau.

## Style

Ponytail rules apply: stdlib/existing-dep first, shortest working diff, no speculative abstraction. Non-trivial logic leaves one runnable check (see `detect.py --selftest` as the pattern). Mark deliberate shortcuts with a `ponytail:` comment naming the ceiling and upgrade path.
