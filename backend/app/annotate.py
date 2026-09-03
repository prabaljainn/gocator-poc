"""Backend API for the Dataset Lab (interactive annotation & curation)."""
import json
import os
from pathlib import Path
from typing import List
import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

import detect
import rec_reader as rr
from . import ml_detector

router = APIRouter(prefix="/api/annotate", tags=["annotate"])

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "custom_dataset"
MANIFEST_FILE = DATA_DIR / "manifest.json"


class Box(BaseModel):
    id: str
    xc: float
    yc: float
    w: float
    h: float
    label: str = "sunflower_head"


class SaveFrameRequest(BaseModel):
    boxes: List[Box]
    verified: bool = True


def _ensure_dirs():
    (DATA_DIR / "images" / "train").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "images" / "val").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "labels" / "val").mkdir(parents=True, exist_ok=True)


def _load_manifest():
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_manifest(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _get_recording_path(source_name: str) -> Path:
    candidates = [
        REPO / source_name,
        Path("/home/prabal/gocator-poc") / source_name,
    ]
    for c in candidates:
        if c.exists():
            return c
    raise HTTPException(404, f"Recording not found: {source_name}")


@router.get("/sources")
def list_sources():
    sources = [
        "tobetsu-data-20260730-1416.rec",
        "3sept.rec"
    ]
    manifest = _load_manifest()
    out = []
    for s in sources:
        try:
            path = _get_recording_path(s)
            h, w, dx, dy, ends = rr.get_rec_info(str(path))
            total_frames = len(ends)
        except Exception:
            total_frames = 0

        verified_count = sum(1 for k, v in manifest.items() if k.startswith(Path(s).stem) and v.get("verified"))
        out.append({
            "name": s,
            "stem": Path(s).stem,
            "total_frames": total_frames,
            "verified_frames": verified_count
        })
    return out


@router.get("/frame/{source}/{frame_idx}")
def get_frame_annotation(source: str, frame_idx: int):
    path = _get_recording_path(source)
    stem = Path(source).stem
    manifest = _load_manifest()
    key = f"{stem}_f{frame_idx:03d}"

    h, w, dx, dy, ends = rr.get_rec_info(str(path))
    if frame_idx < 0 or frame_idx >= len(ends):
        raise HTTPException(400, "Frame index out of bounds")

    # Check if we already have verified annotations
    if key in manifest and manifest[key].get("verified"):
        return {
            "source": source,
            "frame_idx": frame_idx,
            "total_frames": len(ends),
            "verified": True,
            "boxes": manifest[key].get("boxes", []),
            "width": w,
            "height": h,
            "image_url": f"/api/annotate/image/{source}/{frame_idx}.jpg"
        }

    # If not verified yet, seed with current detector candidates
    z16, inten = rr.read_frame(str(path), ends[frame_idx])
    z_mm, i, valid, px_mm = detect.preprocess(z16, inten, dx_mm=dx, dy_mm=dy)
    heads = ml_detector.find_heads(z_mm, i, valid, px_mm)

    h_img, w_img = i.shape[:2]
    seeded_boxes = []
    for idx, h_info in enumerate(heads):
        cx_px, cy_px, r_px = h_info["_circle"]
        bw = min(2.0 * r_px, w_img)
        bh = min(2.0 * r_px, h_img)
        seeded_boxes.append({
            "id": f"box_{idx}",
            "xc": float(np.clip(cx_px / w_img, 0.0, 1.0)),
            "yc": float(np.clip(cy_px / h_img, 0.0, 1.0)),
            "w": float(np.clip(bw / w_img, 0.01, 1.0)),
            "h": float(np.clip(bh / h_img, 0.01, 1.0)),
            "label": "sunflower_head"
        })

    return {
        "source": source,
        "frame_idx": frame_idx,
        "total_frames": len(ends),
        "verified": False,
        "boxes": seeded_boxes,
        "width": w_img,
        "height": h_img,
        "image_url": f"/api/annotate/image/{source}/{frame_idx}.jpg"
    }


@router.get("/image/{source}/{frame_idx}.jpg")
def get_frame_image(source: str, frame_idx: int):
    path = _get_recording_path(source)
    h, w, dx, dy, ends = rr.get_rec_info(str(path))
    if frame_idx < 0 or frame_idx >= len(ends):
        raise HTTPException(400, "Frame index out of range")

    z16, inten = rr.read_frame(str(path), ends[frame_idx])
    z_mm, i, valid, px_mm = detect.preprocess(z16, inten, dx_mm=dx, dy_mm=dy)

    # Render 3D fused composite image
    fused_img, _ = ml_detector.make_fused_image(z_mm, i, valid)
    ok, buf = cv2.imencode(".jpg", fused_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise HTTPException(500, "Failed to encode frame")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.post("/frame/{source}/{frame_idx}")
def save_frame_annotation(source: str, frame_idx: int, req: SaveFrameRequest):
    _ensure_dirs()
    path = _get_recording_path(source)
    stem = Path(source).stem
    key = f"{stem}_f{frame_idx:03d}"

    manifest = _load_manifest()
    manifest[key] = {
        "source": source,
        "frame_idx": frame_idx,
        "verified": req.verified,
        "boxes": [b.dict() for b in req.boxes]
    }
    _save_manifest(manifest)

    # Save to YOLO dataset
    h, w, dx, dy, ends = rr.get_rec_info(str(path))
    z16, inten = rr.read_frame(str(path), ends[frame_idx])
    z_mm, i, valid, px_mm = detect.preprocess(z16, inten, dx_mm=dx, dy_mm=dy)
    fused_img, _ = ml_detector.make_fused_image(z_mm, i, valid)

    is_val = (frame_idx % 5 == 0)
    sub = "val" if is_val else "train"

    img_file = DATA_DIR / "images" / sub / f"{key}.jpg"
    lbl_file = DATA_DIR / "labels" / sub / f"{key}.txt"

    cv2.imwrite(str(img_file), fused_img)
    with open(lbl_file, "w") as f:
        for b in req.boxes:
            f.write(f"0 {b.xc:.6f} {b.yc:.6f} {b.w:.6f} {b.h:.6f}\n")

    return {"status": "saved", "key": key, "box_count": len(req.boxes)}
