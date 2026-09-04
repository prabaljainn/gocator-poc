import json
import os
import sys
import cv2
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import rec_reader as rr
import detect
from backend.app import ml_detector

MANIFEST = ROOT / 'data/custom_dataset/manifest.json'
OUT_DIR = ROOT / 'data/augmented_dataset'

def augment():
    with open(MANIFEST) as f:
        manifest = json.load(f)

    for p in ['images/train', 'images/val', 'labels/train', 'labels/val']:
        (OUT_DIR / p).mkdir(parents=True, exist_ok=True)

    verified_keys = [k for k, v in manifest.items() if v.get('verified') and v.get('boxes')]
    print(f'Augmenting {len(verified_keys)} verified frames with boxes...')

    total_samples = 0
    for idx, key in enumerate(verified_keys):
        entry = manifest[key]
        source = entry['source']
        f_idx = entry['frame_idx']
        boxes = entry['boxes']

        rec_path = ROOT / source
        h, w, dx, dy, ends = rr.get_rec_info(str(rec_path))
        z16, inten = rr.read_frame(str(rec_path), ends[f_idx])
        z_mm, i, valid, px_mm = detect.preprocess(z16, inten, dx_mm=dx, dy_mm=dy)
        img_fused, _ = ml_detector.make_fused_image(z_mm, i, valid)

        is_val = (idx % 5 == 0)
        sub = 'val' if is_val else 'train'

        img_dir = OUT_DIR / 'images' / sub
        lbl_dir = OUT_DIR / 'labels' / sub

        # 1. Original
        cv2.imwrite(str(img_dir / f'{key}.jpg'), img_fused)
        with open(lbl_dir / f'{key}.txt', 'w') as f_out:
            for b in boxes:
                f_out.write(f'0 {b["xc"]:.6f} {b["yc"]:.6f} {b["w"]:.6f} {b["h"]:.6f}\n')
        total_samples += 1

        if not is_val:
            # 2. Horizontal Flip
            img_hf = cv2.flip(img_fused, 1)
            cv2.imwrite(str(img_dir / f'{key}_hf.jpg'), img_hf)
            with open(lbl_dir / f'{key}_hf.txt', 'w') as f_out:
                for b in boxes:
                    f_out.write(f'0 {1.0 - b["xc"]:.6f} {b["yc"]:.6f} {b["w"]:.6f} {b["h"]:.6f}\n')
            total_samples += 1

            # 3. Brightness variations
            for factor, tag in [(0.85, 'dark'), (1.2, 'bright')]:
                img_var = np.clip(img_fused.astype(np.float32) * factor, 0, 255).astype(np.uint8)
                cv2.imwrite(str(img_dir / f'{key}_{tag}.jpg'), img_var)
                with open(lbl_dir / f'{key}_{tag}.txt', 'w') as f_out:
                    for b in boxes:
                        f_out.write(f'0 {b["xc"]:.6f} {b["yc"]:.6f} {b["w"]:.6f} {b["h"]:.6f}\n')
                total_samples += 1

    # dataset.yaml
    yaml_content = f'''path: {OUT_DIR}
train: images/train
val: images/val
names:
  0: sunflower_head
'''
    with open(OUT_DIR / 'dataset.yaml', 'w') as f_out:
        f_out.write(yaml_content)

    print(f'Augmentation complete! Total training samples: {total_samples}')

if __name__ == '__main__':
    augment()
