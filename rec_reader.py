"""Reader for Gocator 2690 .rec recordings (firmware 6.x, Goc.GvSurfaceMsg frames).

Reverse-engineered layout: kDat6-serialized stream. Each frame block carries a
small header (kMsgInfo + Goc.GvSurfaceMsg dims + kStamp), then a Z raster
(big-endian int16, H x W, 0x8000 = invalid) followed by an intensity raster
(uint8, H x W), flush against the next frame's header.
"""
import re
import struct
import numpy as np

# Default/fallback dimensions (Tobetsu recording geometry)
H, W = 3389, 4033
DX_MM = 500.092 / (W - 1)        # X spacing, optically calibrated (trustworthy)
DY_MM = 600.1359375 / (H - 1)    # Y spacing, time-triggered: assumes constant travel speed
# ponytail: Z scale assumed = full 450mm range over int16 span; exact zRes/zOffset not
# yet decoded from the frame header. Fine for relative heights; decode header if
# absolute Z in mm ever matters.
ZRES_MM = 450.0 / 65534
INVALID = -32768

_STAMP_MAGIC = re.escape(bytes([0x78, 0x56, 0x34, 0x12]))  # kStamp magic 0x12345678
_CACHE = {}


def get_rec_info(path):
    """Return (h, w, dx_mm, dy_mm, ends) dynamically parsed from recording headers."""
    path_str = str(path)
    if path_str in _CACHE:
        return _CACHE[path_str]

    mm = np.memmap(path_str, dtype=np.uint8, mode="r")
    stamp_hits = []
    chunk = 256 * 1024 * 1024
    for s in range(0, len(mm), chunk):
        buf = bytes(mm[s:s + chunk + 4])
        stamp_hits += [s + m.start() for m in re.finditer(_STAMP_MAGIC, buf)]
    stamp_hits = sorted(set(stamp_hits))

    if stamp_hits:
        pos0 = stamp_hits[0]
        # In kSerializer, (height, width) as two int64 LE sit 49 bytes before stamp magic
        h, w = struct.unpack("<qq", bytes(mm[pos0 - 49 : pos0 - 49 + 16]))
        # Each frame ends 72 bytes before the next stamp magic (last frame ends at EOF)
        ends = [p - 72 for p in stamp_hits[1:]] + [len(mm)]
    else:
        h, w = H, W
        ends = [len(mm)]

    dx_mm = 500.092 / (w - 1)
    dy_mm = 600.1359375 / (h - 1)
    res = (int(h), int(w), float(dx_mm), float(dy_mm), ends)
    _CACHE[path_str] = res
    return res


def frame_ends(path):
    """Byte offsets of each frame's end (= start of next frame's header)."""
    return get_rec_info(path)[4]


def read_frame(path, end_offset):
    """Return (z16 int16 heightmap, intensity uint8) for frame ending at end_offset."""
    h, w, _, _, _ = get_rec_info(path)
    mm = np.memmap(path, dtype=np.uint8, mode="r")
    z_bytes = h * w * 2
    i_bytes = h * w
    z0 = end_offset - z_bytes - i_bytes
    z = np.frombuffer(mm[z0 : z0 + z_bytes], dtype=">i2").reshape(h, w)
    i = np.frombuffer(mm[z0 + z_bytes : end_offset], dtype=np.uint8).reshape(h, w)
    return z, i


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    h, w, dx, dy, ends = get_rec_info(path)
    z, i = read_frame(path, ends[0])
    valid = (z != INVALID).mean()
    assert len(ends) > 0 and z.shape == (h, w) and 0.01 < valid < 0.99
    print(f"{len(ends)} frames ({h}x{w}, dx={dx:.4f}mm, dy={dy:.4f}mm), frame0 valid={valid:.1%}")
