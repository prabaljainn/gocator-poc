# gocator-poc

Sunflower detection + diameter measurement from Gocator 2690 laser profiler scans.

## Pipeline

1. Extract heightmap + intensity from Gocator replay file (`.rec`)
2. Denoise (median filter, dropout interpolation)
3. Detect flower head (height threshold → connected components → shape filter)
4. Measure diameter (RANSAC circle/ellipse fit, px → mm via scan metadata)

## Hardware

- Gocator 2690 (field scans, replay files)
- DGX Spark (processing, if ML fallback needed)
- MacBook (viewing/analysis)
