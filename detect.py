"""Detect sunflower heads and measure diameter from a Gocator 2690 .rec recording.

Usage:
    python detect.py <file.rec> [frame_idx ...]     # default: all frames
    python detect.py --selftest

Writes out/overlay_<k>.png (detections drawn on intensity) and out/detections.csv.
"""
import csv
import os
import sys

import cv2
import numpy as np

import rec_reader as rr

DS = 4                              # downsample stride on X (raw px are ~0.124mm)
PX_MM = rr.DX_MM * DS               # isotropic mm/px after Y-rescale (~0.50mm)
MIN_DIA_MM, MAX_DIA_MM = 50.0, 350.0   # disc-only diameters run smaller than full heads


def preprocess(z16, inten, dx_mm=rr.DX_MM, dy_mm=rr.DY_MM, z_res_mm=rr.ZRES_MM):
    """Downsample, resample to isotropic mm/px, median-despike.

    Resolutions are arguments because live frames report their own (the sensor's
    active-area settings change them); assuming the recording's constants would
    silently scale every live diameter. Returns (z_mm, i, valid, px_mm).
    """
    z = z16[::DS, ::DS].astype(np.float32)
    i = inten[::DS, ::DS]
    new_h = int(round(z.shape[0] * dy_mm / dx_mm))
    z = cv2.resize(z, (z.shape[1], new_h), interpolation=cv2.INTER_NEAREST)
    i = cv2.resize(i, (i.shape[1], new_h), interpolation=cv2.INTER_NEAREST)
    valid = z != float(rr.INVALID)
    z = cv2.medianBlur(z, 5)                       # kills laser speckle spikes
    valid &= z != float(rr.INVALID)
    z_mm = np.where(valid, z * z_res_mm, np.nan)
    return z_mm, i, valid, dx_mm * DS


TEX_WIN = 9        # local-std window (seed cells are ~4-10px at 0.5mm/px)
TEX_THR = 25.0     # px must exceed this local std to count as "seed texture"
FILL_THR = 0.55    # a disc keeps its circle at least this full of texture
MIN_MEAN_TEX = 40.0  # inside-disc texture; real heads measured 48-55, leaf clusters ~30-37
MAX_HEADS = 6      # per frame; suppression radius 2.5r between picks


def _refine_radius(texbin, cx, cy, r_coarse, step=8):
    """The coarse scan quantizes r to 8px (~4mm); sweep 1px around the winner."""
    h, w = texbin.shape
    best = float(r_coarse)
    for r in range(max(r_coarse - step + 1, 2), r_coarse + step):
        y0, y1 = max(cy - r, 0), min(cy + r + 1, h)
        x0, x1 = max(cx - r, 0), min(cx + r + 1, w)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        m = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
        if texbin[y0:y1, x0:x1][m].mean() >= FILL_THR:
            best = float(r)
    return best


def find_heads(z_mm, i, valid, px_mm=PX_MM):
    """Matched filter: the largest circle >=FILL_THR full of seed texture is a disc.

    Heads read as SOLID high-texture discs; leaves only show texture at thin
    edges/veins, which can't fill a 5cm+ circle. No morphology, no contours —
    ring-breaks and attached leaves don't distort the fit.
    """
    if valid.sum() < 1000:
        return []
    f = i.astype(np.float32)
    mu = cv2.boxFilter(f, -1, (TEX_WIN, TEX_WIN))
    var = cv2.boxFilter(f * f, -1, (TEX_WIN, TEX_WIN)) - mu * mu
    tex = np.sqrt(np.clip(var, 0, None))
    tex[~valid] = 0
    texbin = (tex > TEX_THR).astype(np.float32)

    r_min = int(MIN_DIA_MM / 2 / px_mm)
    r_max = int(min(MAX_DIA_MM, 200.0) / 2 / px_mm)   # discs top out well under 20cm
    best_r = np.zeros(texbin.shape, np.float32)
    best_fill = np.zeros(texbin.shape, np.float32)
    for r in range(r_min, r_max + 1, 8):
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)).astype(np.float32)
        kern /= kern.sum()
        # constant border: reflected borders fake texture beyond the image edge
        fill = cv2.filter2D(texbin, -1, kern, borderType=cv2.BORDER_CONSTANT)
        sel = fill >= FILL_THR
        best_r[sel] = r                     # increasing r: keeps the largest passing radius
        best_fill[sel] = fill[sel]

    bg_z = np.nanmedian(z_mm)
    heads = []
    br = best_r.copy()
    while len(heads) < MAX_HEADS:
        r = float(br.max())
        if r < r_min:
            break
        # among all pixels supporting radius r, center on the best-filled one
        cy_i, cx_i = np.unravel_index(int((best_fill * (br == r)).argmax()), br.shape)
        cv2.circle(br, (int(cx_i), int(cy_i)), int(2.5 * r), 0, -1)  # suppress neighborhood
        r = _refine_radius(texbin, int(cx_i), int(cy_i), int(r))
        circ = np.zeros(texbin.shape, np.uint8)
        cv2.circle(circ, (int(cx_i), int(cy_i)), max(int(0.85 * r), 1), 1, -1)
        in_circ = circ > 0
        valid_frac = float(valid[in_circ].mean())   # a real disc is solid data, not gaps
        tex_in = float(tex[in_circ].mean())
        mean_h = float(np.nanmean(np.where(in_circ, z_mm, np.nan))) - bg_z
        edge = int(r) + 2
        truncated = (cx_i < edge or cy_i < edge or
                     cx_i > texbin.shape[1] - edge or cy_i > texbin.shape[0] - edge)
        heads.append({
            "cx_mm": cx_i * px_mm, "cy_mm": cy_i * px_mm,
            "dia_mm": 2 * r * px_mm,                # matched-filter circle = disc diameter
            "valid_frac": valid_frac, "tex_in": tex_in,
            "height_mm": mean_h, "truncated": truncated,
            "accepted": valid_frac >= 0.70 and tex_in >= MIN_MEAN_TEX,
            "_circle": (int(cx_i), int(cy_i), int(r)),
        })
    return heads


def overlay(i, heads):
    img = cv2.cvtColor(i, cv2.COLOR_GRAY2BGR)
    for h in heads:
        cx, cy, r = h["_circle"]
        color = (0, 220, 0) if h["accepted"] else (0, 120, 255)
        cv2.circle(img, (cx, cy), r, color, 2)
        if h["accepted"]:
            cv2.putText(img, f'{h["dia_mm"]:.0f}mm', (cx - 40, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
    return img


def contact_sheet(tiles, out_path, tile_px=220, cols=8):
    """One glance over every accepted detection: cropped, labeled, gridded."""
    if not tiles:
        return
    rows_n = (len(tiles) + cols - 1) // cols
    sheet = np.zeros((rows_n * tile_px, cols * tile_px, 3), np.uint8)
    for n, (label, crop) in enumerate(tiles):
        t = cv2.resize(crop, (tile_px, tile_px), interpolation=cv2.INTER_AREA)
        cv2.putText(t, label, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
        r0, c0 = (n // cols) * tile_px, (n % cols) * tile_px
        sheet[r0:r0 + tile_px, c0:c0 + tile_px] = t
    cv2.imwrite(out_path, sheet)


def run(rec_path, frames=None, out_dir="out"):
    os.makedirs(out_dir, exist_ok=True)
    ends = rr.frame_ends(rec_path)
    frames = frames if frames else range(len(ends))
    rows, tiles = [], []
    for k in frames:
        z16, inten = rr.read_frame(rec_path, ends[k])
        z_mm, i, valid, px_mm = preprocess(z16, inten)
        heads = find_heads(z_mm, i, valid, px_mm)
        cv2.imwrite(f"{out_dir}/overlay_{k:02d}.png", overlay(i, heads))
        for h in heads:
            rows.append({"frame": k, **{k2: (round(v, 1) if isinstance(v, float) else v)
                                        for k2, v in h.items() if not k2.startswith("_")}})
        acc = [h for h in heads if h["accepted"]]
        img = overlay(i, heads)
        for h in acc:
            cx, cy, r = h["_circle"]
            m = int(1.6 * r)
            crop = img[max(cy - m, 0):cy + m, max(cx - m, 0):cx + m]
            if crop.size:
                tiles.append((f'f{k} {h["dia_mm"]:.0f}mm', crop))
        print(f"frame {k:2d}: {len(acc)} head(s) " +
              ", ".join(f'{h["dia_mm"]:.0f}mm' for h in acc))
    contact_sheet(tiles, f"{out_dir}/review.png")
    if rows:
        with open(f"{out_dir}/detections.csv", "w", newline="") as f:
            wtr = csv.DictWriter(f, fieldnames=rows[0].keys())
            wtr.writeheader()
            wtr.writerows(rows)
    print(f"wrote {out_dir}/detections.csv ({len(rows)} candidates)")


def selftest():
    """Synthetic disc of known diameter must measure within 5%."""
    hpx, wpx = 1400, 2000    # 200mm disc = 1613 raw px in X; canvas must fit it
    z16 = np.full((hpx, wpx), rr.INVALID, np.int16)
    inten = np.zeros((hpx, wpx), np.uint8)
    dia_mm = 200.0
    r_px = int(dia_mm / 2 / rr.DX_MM / DS) * DS  # radius in raw px
    yy, xx = np.ogrid[:hpx, :wpx]
    # draw in isotropic mm space mapped back to anisotropic raw px
    disc = ((xx - 1000) * rr.DX_MM) ** 2 + ((yy - 700) * rr.DY_MM) ** 2 <= (dia_mm / 2) ** 2
    z16[disc] = 5000
    rng = np.random.default_rng(0)
    inten[disc] = rng.integers(40, 240, int(disc.sum()))  # seed-like speckle texture
    inten[~disc] = 30                                     # smooth background, zero texture
    z16[~disc] = 1000
    z_mm, i, valid, px_mm = preprocess(z16, inten)
    heads = [h for h in find_heads(z_mm, i, valid, px_mm) if h["accepted"]]
    assert len(heads) == 1, f"expected 1 head, got {len(heads)}"
    err = abs(heads[0]["dia_mm"] - dia_mm) / dia_mm
    assert err < 0.05, f"diameter {heads[0]['dia_mm']:.1f} vs {dia_mm} ({err:.1%})"
    print(f"selftest ok: {heads[0]['dia_mm']:.1f}mm vs {dia_mm}mm ({err:.1%} err)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run(sys.argv[1], [int(a) for a in sys.argv[2:]])
