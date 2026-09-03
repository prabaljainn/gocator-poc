"""Dataset builder for YOLOv8 sunflower head detector.

Extracts isotropic intensity frames from .rec recordings, labels detected heads
using the refined 3D-gated detector, and applies augmentations (flips,
brightness adjustments) to create a robust YOLO training dataset.
"""
import os
import sys
import random
import cv2
import numpy as np
import yaml
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rec_reader as rr
import detect


def extract_and_label_recording(rec_path, out_dir, augment=True):
    images_train = Path(out_dir) / "images" / "train"
    images_val = Path(out_dir) / "images" / "val"
    labels_train = Path(out_dir) / "labels" / "train"
    labels_val = Path(out_dir) / "labels" / "val"

    for p in [images_train, images_val, labels_train, labels_val]:
        p.mkdir(parents=True, exist_ok=True)

    h, w, dx_mm, dy_mm, ends = rr.get_rec_info(rec_path)
    stem = Path(rec_path).stem

    sample_count = 0
    head_count = 0

    for k in range(len(ends)):
        z16, inten = rr.read_frame(rec_path, ends[k])
        z_mm, i, valid, px_mm = detect.preprocess(z16, inten, dx_mm=dx_mm, dy_mm=dy_mm)
        heads = [h for h in detect.find_heads(z_mm, i, valid, px_mm) if h["accepted"]]

        img = cv2.cvtColor(i, cv2.COLOR_GRAY2BGR)
        h_img, w_img = img.shape[:2]

        boxes = []
        for h in heads:
            cx_px, cy_px, r_px = h["_circle"]
            bw = min(2.1 * r_px, w_img)
            bh = min(2.1 * r_px, h_img)
            x_c = np.clip(cx_px / w_img, 0.0, 1.0)
            y_c = np.clip(cy_px / h_img, 0.0, 1.0)
            w_norm = np.clip(bw / w_img, 0.01, 1.0)
            h_norm = np.clip(bh / h_img, 0.01, 1.0)
            boxes.append((0, x_c, y_c, w_norm, h_norm))

        # Split 80% train, 20% val by frame index
        is_val = (k % 5 == 0)
        img_dir = images_val if is_val else images_train
        lbl_dir = labels_val if is_val else labels_train

        base_name = f"{stem}_f{k:03d}"
        cv2.imwrite(str(img_dir / f"{base_name}.jpg"), img)
        _write_labels(lbl_dir / f"{base_name}.txt", boxes)
        sample_count += 1
        head_count += len(boxes)

        if augment and not is_val and boxes:
            # 1. Horizontal flip
            img_hf = cv2.flip(img, 1)
            boxes_hf = [(cls_id, 1.0 - xc, yc, bw, bh) for cls_id, xc, yc, bw, bh in boxes]
            cv2.imwrite(str(img_dir / f"{base_name}_hf.jpg"), img_hf)
            _write_labels(lbl_dir / f"{base_name}_hf.txt", boxes_hf)
            sample_count += 1

            # 2. Brightness variations
            for factor, tag in [(0.75, "dark"), (1.3, "bright")]:
                img_br = np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)
                cv2.imwrite(str(img_dir / f"{base_name}_{tag}.jpg"), img_br)
                _write_labels(lbl_dir / f"{base_name}_{tag}.txt", boxes)
                sample_count += 1

    return sample_count, head_count


def _write_labels(path, boxes):
    with open(path, "w") as f:
        for cls_id, xc, yc, bw, bh in boxes:
            f.write(f"{cls_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n")


def build_dataset(rec_paths, dataset_dir="data/dataset"):
    total_samples = 0
    total_heads = 0
    for path in rec_paths:
        if not os.path.exists(path):
            print(f"Skipping non-existent recording: {path}")
            continue
        print(f"Processing {path}...")
        s, h = extract_and_label_recording(path, dataset_dir)
        total_samples += s
        total_heads += h

    dataset_yaml = {
        "path": os.path.abspath(dataset_dir),
        "train": "images/train",
        "val": "images/val",
        "names": {
            0: "sunflower_head"
        }
    }
    yaml_path = Path(dataset_dir) / "dataset.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(dataset_yaml, f, sort_keys=False)

    print(f"\nDataset build complete! Output at {dataset_dir}")
    print(f"Total samples (with augmentations): {total_samples}")
    print(f"Base annotated heads: {total_heads}")
    print(f"Config written to {yaml_path}")


if __name__ == "__main__":
    recs = sys.argv[1:] if len(sys.argv) > 1 else [
        "tobetsu-data-20260730-1416.rec",
        "3sept.rec"
    ]
    build_dataset(recs)
