# gocator-poc

Sunflower head detection + diameter measurement from Gocator 2690 laser profiler scans (Tobetsu field data). Working offline pipeline; live field system designed and in progress.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install numpy scipy opencv-python-headless pillow
.venv/bin/python detect.py --selftest
.venv/bin/python detect.py tobetsu-data-20260730-1416.rec   # → out/ (overlays, review.png, detections.csv)
```

Verified result on the Tobetsu recording: 55 heads across 42 frames, disc diameters 51–94 mm, zero visible false positives (`out/review.png`).

## How it works

`rec_reader.py` parses the sensor's proprietary `.rec` replay directly ([docs/rec-format.md](docs/rec-format.md)); `detect.py` finds heads with a seed-texture matched filter — the largest circle ≥55 % full of texture is a disc — and measures diameter against the optically calibrated X axis.

## Docs

- [docs/architecture.md](docs/architecture.md) — live system design (sensor → DGX Spark service → React UI)
- [docs/rec-format.md](docs/rec-format.md) — reverse-engineered .rec format
- [docs/decisions.md](docs/decisions.md) — decision log, including approaches that failed
- [CLAUDE.md](CLAUDE.md) — agent/dev guide: commands, invariants, gotchas

## Hardware roles

- **Gocator 2690** — field scanning (500×600 mm surfaces, 0.124 mm/px, co-registered intensity)
- **DGX Spark** — v1 live edge box (GoSDK acquisition + detection + API), later the training box if quality grading needs ML
- **MacBook** — viewing, review, development (GoSDK has no macOS build)
