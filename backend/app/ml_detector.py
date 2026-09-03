"""Deep Learning detector for Gocator sunflower heads.

Combines YOLOv8 neural object localization (high-confidence semantic filtering)
with 3D Gocator heightmap metrology for calibrated millimeter measurements.
"""
from pathlib import Path
import cv2
import numpy as np
import rec_reader as rr
import detect

DEFAULT_WEIGHTS = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "sunflower_yolov8n.onnx"
FALLBACK_PT = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "sunflower_yolov8n" / "weights" / "best.pt"

_MODEL = None


def get_detector(weights_path=None):
    """Singleton getter for YOLO model."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    path = weights_path or (DEFAULT_WEIGHTS if DEFAULT_WEIGHTS.exists() else FALLBACK_PT)
    if not path.exists():
        return None

    try:
        from ultralytics import YOLO
        _MODEL = YOLO(str(path))
        return _MODEL
    except Exception as e:
        print(f"Warning: failed to load ML detector ({e}), falling back to classical detector")
        return None


def find_heads(z_mm, i, valid, px_mm=detect.PX_MM, conf_thr=0.40):
    """Detect sunflower heads using YOLOv8, refined with 3D elevation metrology.

    Falls back to classical detect.find_heads if the neural model is not loaded.
    """
    model = get_detector()
    if model is None:
        return detect.find_heads(z_mm, i, valid, px_mm)

    if valid.sum() < 1000:
        return []

    img_bgr = cv2.cvtColor(i, cv2.COLOR_GRAY2BGR)
    h_img, w_img = img_bgr.shape[:2]

    results = model(img_bgr, conf=conf_thr, verbose=False)
    if not results or len(results[0].boxes) == 0:
        return []

    valid_z = z_mm[valid]
    bg_z = float(np.percentile(valid_z, 20)) if len(valid_z) else 0.0

    heads = []
    boxes = results[0].boxes.xyxy.cpu().numpy()
    confs = results[0].boxes.conf.cpu().numpy()

    # Precompute texture map for boundary refinement
    f = i.astype(np.float32)
    mu = cv2.boxFilter(f, -1, (detect.TEX_WIN, detect.TEX_WIN))
    var = cv2.boxFilter(f * f, -1, (detect.TEX_WIN, detect.TEX_WIN)) - mu * mu
    tex = np.sqrt(np.clip(var, 0, None))
    tex[~valid] = 0
    texbin = (tex > detect.TEX_THR).astype(np.float32)

    for (x1, y1, x2, y2), conf in zip(boxes, confs):
        cx_i = int(round((x1 + x2) / 2.0))
        cy_i = int(round((y1 + y2) / 2.0))
        dia_px = float(x2 - x1)
        r = int(round(dia_px / 2.0))

        # Refine center to local mass centroid inside the box
        y_min, y_max = max(int(y1), 0), min(int(y2), h_img)
        x_min, x_max = max(int(x1), 0), min(int(x2), w_img)
        box_valid = valid[y_min:y_max, x_min:x_max]
        if box_valid.any():
            yy, xx = np.ogrid[y_min:y_max, x_min:x_max]
            cx_i = int(round((xx * box_valid).sum() / box_valid.sum()))
            cy_i = int(round((yy * box_valid).sum() / box_valid.sum()))

        # Refine radius with boundary detection
        r_refined = detect._refine_radius(texbin, cx_i, cy_i, r, step=8, r_min=int(15.0 / px_mm))

        circ = np.zeros(texbin.shape, np.uint8)
        cv2.circle(circ, (cx_i, cy_i), max(int(0.85 * r_refined), 1), 1, -1)
        in_circ = circ > 0
        valid_frac = float(valid[in_circ].mean()) if in_circ.any() else 0.0
        tex_in = float(tex[in_circ].mean()) if in_circ.any() else 0.0
        mean_h = float(np.nanmean(np.where(in_circ, z_mm, np.nan))) - bg_z

        edge = int(r_refined) + 2
        truncated = (cx_i < edge or cy_i < edge or cx_i > w_img - edge or cy_i > h_img - edge)

        dia_mm = 2.0 * r_refined * px_mm

        heads.append({
            "cx_mm": cx_i * px_mm,
            "cy_mm": cy_i * px_mm,
            "dia_mm": dia_mm,
            "valid_frac": valid_frac,
            "tex_in": tex_in,
            "height_mm": mean_h,
            "truncated": truncated,
            "accepted": True,
            "_circle": (int(cx_i), int(cy_i), int(r_refined)),
            "_conf": float(conf)
        })

    return heads
