"""Export full ML detection results and review sheet for a Gocator recording."""
import os
import sys
import csv
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rec_reader as rr
import detect
from backend.app import ml_detector


def export_recording(rec_path, out_dir="out"):
    os.makedirs(out_dir, exist_ok=True)
    stem = Path(rec_path).stem
    h, w, dx_mm, dy_mm, ends = rr.get_rec_info(rec_path)
    
    csv_path = Path(out_dir) / f"{stem}_detections.csv"
    review_path = Path(out_dir) / f"{stem}_review.png"

    rows = []
    tiles = []

    print(f"Exporting results for {rec_path} ({len(ends)} frames)...")

    for k in range(len(ends)):
        z16, inten = rr.read_frame(rec_path, ends[k])
        z_mm, i, valid, px_mm = detect.preprocess(z16, inten, dx_mm=dx_mm, dy_mm=dy_mm)
        heads = ml_detector.find_heads(z_mm, i, valid, px_mm)

        img = detect.overlay(i, heads)

        for idx, h_info in enumerate(heads):
            cx, cy, r = h_info["_circle"]
            m = int(1.6 * r)
            crop = img[max(cy - m, 0):min(cy + m, img.shape[0]),
                       max(cx - m, 0):min(cx + m, img.shape[1])]
            if crop.size:
                tiles.append((f"f{k} {h_info['dia_mm']:.0f}mm", crop))

            rows.append({
                "recording": stem,
                "frame_idx": k,
                "head_idx": idx,
                "dia_mm": round(h_info["dia_mm"], 1),
                "cx_mm": round(h_info["cx_mm"], 1),
                "cy_mm": round(h_info["cy_mm"], 1),
                "height_mm": round(h_info["height_mm"], 1),
                "confidence": round(h_info.get("_conf", 1.0), 3),
                "valid_frac": round(h_info["valid_frac"], 2),
                "tex_in": round(h_info["tex_in"], 1),
            })

        head_dias = [f"{h_info['dia_mm']:.0f}mm" for h_info in heads]
        print(f"  frame {k:2d}: {len(heads)} head(s) -> {', '.join(head_dias) if head_dias else 'none'}")

    # Write CSV
    if rows:
        with open(csv_path, "w", newline="") as f:
            wtr = csv.DictWriter(f, fieldnames=rows[0].keys())
            wtr.writeheader()
            wtr.writerows(rows)
        print(f"\nSaved CSV: {csv_path} ({len(rows)} detections)")

    # Write Contact Sheet
    if tiles:
        detect.contact_sheet(tiles, str(review_path), tile_px=220, cols=8)
        print(f"Saved Review Sheet: {review_path} ({len(tiles)} tiles)")

    return rows


if __name__ == "__main__":
    rec = sys.argv[1] if len(sys.argv) > 1 else "tobetsu-data-20260730-1416.rec"
    export_recording(rec)
