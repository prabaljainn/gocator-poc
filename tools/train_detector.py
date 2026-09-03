"""Train YOLOv8n detector on Gocator sunflower dataset."""
import os
import sys
from pathlib import Path
from ultralytics import YOLO


def train(dataset_yaml="data/dataset/dataset.yaml", epochs=30, img_size=640, out_dir="data/models"):
    os.makedirs(out_dir, exist_ok=True)

    # Initialize pretrained YOLOv8n
    model = YOLO("yolov8n.pt")

    # Train on GPU 0
    results = model.train(
        data=dataset_yaml,
        epochs=epochs,
        imgsz=img_size,
        batch=16,
        device=0,
        workers=4,
        project=out_dir,
        name="sunflower_yolov8n",
        exist_ok=True,
        plots=True
    )

    best_pt = Path(out_dir) / "sunflower_yolov8n" / "weights" / "best.pt"
    print(f"\nTraining complete! Best weights saved at: {best_pt}")

    if best_pt.exists():
        best_model = YOLO(str(best_pt))
        onnx_path = best_model.export(format="onnx", imgsz=img_size, dynamic=True)
        print(f"Exported ONNX model at: {onnx_path}")


if __name__ == "__main__":
    yaml_path = sys.argv[1] if len(sys.argv) > 1 else "data/dataset/dataset.yaml"
    train(yaml_path)
