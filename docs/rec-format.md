# Gocator .rec Format (reverse-engineered)

What we learned by byte-scanning `tobetsu-data-20260730-1416.rec` (firmware 6.x, Gocator 2690, Surface mode). No public spec exists; `rec_reader.py` implements this. Verified by extracting all 42 frames and visually confirming the imagery.

## Container

kDat6/kSerializer stream (LMI's kApi object serialization). Starts with a type map (`kMap-0`, `kText128-0`, `kObject-0`, `Recorder.1`, `Simulator.1`, …). The sensor's full configuration XML is embedded near the head of the file — grep for `<Trigger>`, `<SurfaceGeneration>`, `<IntensityEnabled>` to recover scan geometry without any SDK.

## Frame layout

Each frame block:

```
[kMsgInfo ~small] ["Goc.GvSurfaceMsg-13"] [height int64 LE] [width int64 LE] [1] [2]
[kStamp-1 · magic 0x12345678 · timestamp µs · encoder]
[... remaining header, size varies by a few bytes ...]
[Z raster    : height × width × int16 BIG-endian]   ← 27,335,674 B for 3389×4033
[intensity   : height × width × uint8]              ← 13,667,837 B
→ intensity ends FLUSH against the next frame's kMsgInfo
```

## The two rules that make parsing work

1. **Anchor on the width field.** `4033` as int64 little-endian (`C1 0F 00 00 00 00 00 00`) sits at a fixed +72 bytes into each frame's kMsgInfo block. Scanning the whole file for this pattern finds exactly one hit per frame (42 total).
2. **Slice backwards from the *next* anchor.** Header size varies by tens of bytes between frames, but rasters always end flush at the next header. So: `z_start = next_anchor_start − Z_BYTES − I_BYTES`. The last frame uses EOF.

## Endianness trap

The kSerializer header fields (dims, counts) are **little-endian**, but the raster payload is **network big-endian** (`>i2`). Decoding Z as LE produces ring/contour banding artifacts inside objects — if you see those, you have the byte order wrong.

## Values

| Field | Encoding | Notes |
|---|---|---|
| Z invalid | `0x8000` (−32768 as int16) | ~83–85 % of field pixels (dropouts/out-of-range) |
| Z scale | ~6.87 µm/count assumed (450 mm range / int16 span) | exact zRes/zOffset live in the unparsed header remainder — decode if absolute Z ever matters |
| X spacing | 0.124 mm/px (500.092 mm / 4032) | optical calibration — trustworthy |
| Y spacing | 0.177 mm/px (600.136 mm / 3388) | time-triggered — assumes constant travel speed |
| Stamp magic | `0x12345678` | start of kStamp payload |

## Tobetsu recording specifics

1,722,335,226 bytes · 42 frames · ~41,003,800 B/frame (first frame +28 B of extra header) · surfaces 3389 × 4033 · fixed length 600 mm · intensity enabled · time trigger at max rate (994 Hz), no encoder.
