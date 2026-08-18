"""Reader for Gocator 2690 .rec recordings (firmware 6.x, Goc.GvSurfaceMsg frames).

Reverse-engineered layout: kDat6-serialized stream. Each frame block carries a
small header (kMsgInfo + Goc.GvSurfaceMsg dims + kStamp), then a Z raster
(big-endian int16, H x W, 0x8000 = invalid) followed by an intensity raster
(uint8, H x W), flush against the next frame's header. Frames are anchored by
the little-endian int64 width field (4033) that sits 72 bytes into kMsgInfo.
"""
import re

import numpy as np

H, W = 3389, 4033
DX_MM = 500.092 / (W - 1)        # X spacing, optically calibrated (trustworthy)
DY_MM = 600.1359375 / (H - 1)    # Y spacing, time-triggered: assumes constant travel speed
# ponytail: Z scale assumed = full 450mm range over int16 span; exact zRes/zOffset not
# yet decoded from the frame header. Fine for relative heights; decode header if
# absolute Z in mm ever matters.
ZRES_MM = 450.0 / 65534
INVALID = -32768

_Z_BYTES = H * W * 2
_I_BYTES = H * W
_WIDTH_FIELD = re.escape(bytes([0xC1, 0x0F, 0, 0, 0, 0, 0, 0]))  # int64 LE 4033


def frame_ends(path):
    """Byte offsets of each frame's end (= start of next frame's header)."""
    mm = np.memmap(path, dtype=np.uint8, mode="r")
    hits = []
    chunk = 256 * 1024 * 1024
    for s in range(0, len(mm), chunk):
        buf = bytes(mm[s:s + chunk + 8])
        hits += [s + m.start() for m in re.finditer(_WIDTH_FIELD, buf)]
    hits = sorted(set(hits))
    return [h - 72 for h in hits[1:]] + [len(mm)]


def read_frame(path, end_offset):
    """Return (z16 int16 heightmap, intensity uint8) for frame ending at end_offset."""
    mm = np.memmap(path, dtype=np.uint8, mode="r")
    z0 = end_offset - _Z_BYTES - _I_BYTES
    z = np.frombuffer(mm[z0:z0 + _Z_BYTES], dtype=">i2").reshape(H, W)
    i = np.frombuffer(mm[z0 + _Z_BYTES:end_offset], dtype=np.uint8).reshape(H, W)
    return z, i


if __name__ == "__main__":
    import sys
    ends = frame_ends(sys.argv[1])
    z, i = read_frame(sys.argv[1], ends[0])
    valid = (z != INVALID).mean()
    assert len(ends) > 0 and z.shape == (H, W) and 0.01 < valid < 0.99
    print(f"{len(ends)} frames, frame0 valid={valid:.1%}")
