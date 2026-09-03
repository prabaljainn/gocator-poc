"""Dataset builder for multi-modal YOLOv8-seg (Instance Segmentation).

Generates 3D multi-modal composite images and polygon segmentation annotations:
  Channel 0: Intensity (reflectance & seed texture)
  Channel 1: Normalized 3D Relative Height (Z - Z_bg)
  Channel 2: 3D Surface Gradient (depth boundary steps)
Annotation Format (YOLO-seg):
  <class_id> <x1> <y1> <x2> <y2> ... <xN> <yN>
"""
import os
import sys
import math
import cv2
import numpy as np
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rec_reader as rr
import detect


def make_fused_image(z_mm, i, valid):
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

    return cv2.merge([ch0, ch1, ch2])


def _circle_to_polygon(cx_px, cy_px, r_px, w_img, h_img, n_points=18):
    coords = []
    for step in range(n_points):
        theta = 2.0 * math.pi * step / float(n_points)
        px = cx_px + r_px * math.cos(theta)
        py = cy_px + r_px * math.sin(theta)
        norm_x = np.clip(px / float(w_img), 0.0, 1.0)
        norm_y = np.clip(py / float(h_img), 0.0, 1.0)
        coords.append(norm_x)
        coords.append(norm_y)
    return coords


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

        fused_img = make_fused_image(z_mm, i, valid)
        h_img, w_img = fused_img.shape[:2]

        polys = []
        for h_info in heads:
            cx_px, cy_px, r_px = h_info["_circle"]
            poly_coords = _circle_to_polygon(cx_px, cy_px, r_px, w_img, h_img)
            polys.append((0, poly_coords))

        is_val = (k % 5 == 0)
        img_dir = images_val if is_val else images_train
        lbl_dir = labels_val if is_val else labels_train

        base_name = f"{stem}_f{k:03d}"
        cv2.imwrite(str(img_dir / f"{base_name}.jpg"), fused_img)
        _write_seg_labels(lbl_dir / f"{base_name}.txt", polys)
        sample_count += 1
        head_count += len(polys)

        if augment and not is_val and polys:
            # Horizontal flip
            img_hf = cv2.flip(fused_img, 1)
            polys_hf = []
            for cls_id, coords in polys:
                hf_coords = []
                for idx in range(0, len(coords), 2):
                    hf_coords.append(1.0 - coords[idx])
                    hf_coords.append(coords[idx + 1])
                polys_hf.append((cls_id, hf_coords))

            cv2.imwrite(str(img_dir / f"{base_name}_hf.jpg"), img_hf)
            _write_seg_labels(lbl_dir / f"{base_name}_hf.txt", polys_hf)
            sample_count += 1

            # Brightness variations
            for factor, tag in [(0.8, "dark"), (1.25, "bright")]:
                img_var = np.clip(fused_img.astype(np.float32) * factor, 0, 255).astype(np.uint8)
                cv2.imwrite(str(img_dir / f"{base_name}_{tag}.jpg"), img_var)
                _write_seg_labels(lbl_dir / f"{base_name}_{tag}.txt", polys)
                sample_count += 1

    return sample_count, head_count


def _write_seg_labels(path, polys):
    with open(path, "w") as f:
        for cls_id, coords in polys:
            line = f"{cls_id} " + " ".join(f"{c:.6f}" for c in coords)
            f.write(line + "\n")


def build_dataset(rec_paths, dataset_dir="data/dataset"):
    total_samples = 0
    total_heads = 0
    for path in rec_paths:
        if not os.path.exists(path):
            print(f"Skipping: {path}")
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

    print(f"\nSegmentation dataset build complete! ({total_samples} samples, {total_heads} heads)")


if __name__ == "__main__":
    recs = sys.argv[1:] if len(sys.argv) > 1 else [
        "tobetsu-data-20260730-1416.rec",
        "3sept.rec"
    ]
    build_dataset(recs)
