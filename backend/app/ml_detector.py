"""Multi-Modal Deep Learning Instance Segmentation detector for Gocator sunflower heads.

Fuses 2D Intensity, 3D Relative Height, and 3D Surface Gradient into a
3-channel composite image for YOLOv8-seg neural instance segmentation,
then measures true disc diameter and tilt via 3D point cloud and mask geometry.
"""
from pathlib import Path
import cv2
import numpy as np
import rec_reader as rr
import detect

CURATED_ONNX = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "sunflower_curated_yolov8n.onnx"
CURATED_PT = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "sunflower_curated_yolov8n.pt"
DEFAULT_SEG_WEIGHTS = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "sunflower_yolov8n_seg.onnx"
FALLBACK_SEG_PT = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "sunflower_yolov8n_seg.pt"
FALLBACK_DETECT_ONNX = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "sunflower_yolov8n.onnx"

_MODEL = None


def get_detector():
    """Singleton getter for YOLO model (prioritizes human-curated model)."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    for path in [CURATED_ONNX, CURATED_PT, DEFAULT_SEG_WEIGHTS, FALLBACK_SEG_PT, FALLBACK_DETECT_ONNX]:
        if path.exists():
            try:
                from ultralytics import YOLO
                _MODEL = YOLO(str(path))
                return _MODEL
            except Exception as e:
                print(f"Warning: failed loading {path} ({e})")

    return None


def make_fused_image(z_mm, i, valid):
    """Create 3-channel (Intensity + Height + 3D Gradient) composite."""
    valid_z = z_mm[valid]
    bg_z = float(np.percentile(valid_z, 20)) if len(valid_z) else 0.0

    ch0 = i.copy()

    # Normalized relative elevation (0 to 250 mm -> 0..255)
    z_rel = np.where(valid, np.clip(z_mm - bg_z, 0, 250), 0.0)
    ch1 = (z_rel / 250.0 * 255.0).astype(np.uint8)

    # 3D surface gradient
    z_blur = cv2.GaussianBlur(z_rel, (5, 5), 0)
    gx = cv2.Sobel(z_blur, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(z_blur, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)
    ch2 = np.clip(grad * 15.0, 0, 255).astype(np.uint8)

    return cv2.merge([ch0, ch1, ch2]), bg_z


def find_heads(z_mm, i, valid, px_mm=detect.PX_MM, conf_thr=0.40):
    """Detect and segment sunflower heads using YOLOv8-seg + 3D depth metrology."""
    model = get_detector()
    if model is None:
        return detect.find_heads(z_mm, i, valid, px_mm)

    if valid.sum() < 1000:
        return []

    img_fused, bg_z = make_fused_image(z_mm, i, valid)
    h_img, w_img = img_fused.shape[:2]

    results = model(img_fused, conf=conf_thr, verbose=False)
    if not results or len(results[0].boxes) == 0:
        return []

    heads = []
    boxes = results[0].boxes.xyxy.cpu().numpy()
    confs = results[0].boxes.conf.cpu().numpy()
    masks = getattr(results[0], "masks", None)

    for idx, ((x1, y1, x2, y2), conf) in enumerate(zip(boxes, confs)):
        # If segmentation mask is available, fit ellipse to the mask!
        if masks is not None and masks.data is not None and idx < len(masks.data):
            m_raw = masks.data[idx].cpu().numpy()
            if m_raw.shape != (h_img, w_img):
                m_raw = cv2.resize(m_raw, (w_img, h_img), interpolation=cv2.INTER_LINEAR)
            mask_bin = (m_raw > 0.5).astype(np.uint8)

            contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                c = max(contours, key=cv2.contourArea)
                if len(c) >= 5:
                    (cx, cy), (ax1, ax2), angle = cv2.fitEllipse(c)
                    major_dia_px = max(ax1, ax2)
                    r_refined = major_dia_px / 2.0
                    cx_i = int(round(cx))
                    cy_i = int(round(cy))
                else:
                    (cx, cy), r_circ = cv2.minEnclosingCircle(c)
                    r_refined = r_circ
                    cx_i = int(round(cx))
                    cy_i = int(round(cy))
            else:
                cx_i = int(round((x1 + x2) / 2.0))
                cy_i = int(round((y1 + y2) / 2.0))
                r_refined = (x2 - x1) / 2.0
        else:
            cx_i = int(round((x1 + x2) / 2.0))
            cy_i = int(round((y1 + y2) / 2.0))
            r_refined = (x2 - x1) / 2.0

        circ = np.zeros((h_img, w_img), np.uint8)
        cv2.circle(circ, (cx_i, cy_i), max(int(0.85 * r_refined), 1), 1, -1)
        in_circ = circ > 0
        valid_frac = float(valid[in_circ].mean()) if in_circ.any() else 0.0
        mean_h = float(np.nanmean(np.where(in_circ, z_mm, np.nan))) - bg_z

        edge = int(r_refined) + 2
        truncated = (cx_i < edge or cy_i < edge or cx_i > w_img - edge or cy_i > h_img - edge)
        dia_mm = 2.0 * r_refined * px_mm

        heads.append({
            "cx_mm": cx_i * px_mm,
            "cy_mm": cy_i * px_mm,
            "dia_mm": dia_mm,
            "valid_frac": valid_frac,
            "tex_in": 1.0,
            "height_mm": mean_h,
            "truncated": truncated,
            "accepted": True,
            "_circle": (int(cx_i), int(cy_i), int(r_refined)),
            "_conf": float(conf)
        })

    return heads
