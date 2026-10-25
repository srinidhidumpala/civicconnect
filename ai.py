"""Optional YOLOv8 hook. Never blocks complaint submission.
If model/best.pt (or $YOLO_MODEL) is missing, or ultralytics is not installed,
we return category=None with an honest note. Nothing is fabricated."""
import os

MODEL_PATH = os.environ.get("YOLO_MODEL", os.path.join(os.path.dirname(__file__), "model", "best.pt"))

# Map YOUR model's class names -> categories used by the app. Edit to match your weights.
CLASS_MAP = {
    "pothole": "Pothole", "damaged_road": "Damaged Road", "road_damage": "Damaged Road",
    "garbage": "Garbage Accumulation", "trash": "Garbage Accumulation",
    "streetlight": "Broken Streetlight", "water_leak": "Water Leakage",
    "waterlogging": "Waterlogging", "drainage": "Drainage Problem",
    "fire": "Fire-Related Issue",
}
_model = None

def analyze(image_path):
    global _model
    if not os.path.exists(MODEL_PATH):
        return {"category": None, "confidence": None,
                "note": "AI model not configured (no weights file). Citizen-selected category used."}
    try:
        if _model is None:
            from ultralytics import YOLO
            _model = YOLO(MODEL_PATH)
        res = _model(image_path, verbose=False)[0]
        if res.boxes is None or len(res.boxes) == 0:
            return {"category": None, "confidence": None, "note": "AI ran but detected no known civic issue."}
        i = int(res.boxes.conf.argmax())
        name = res.names[int(res.boxes.cls[i])].lower()
        conf = float(res.boxes.conf[i])
        cat = CLASS_MAP.get(name)
        note = "YOLOv8 detection." if cat else f"YOLOv8 detected '{name}', which is not mapped to an app category."
        return {"category": cat, "confidence": round(conf, 3), "note": note}
    except Exception as e:  # AI must never break the core workflow
        return {"category": None, "confidence": None, "note": f"AI inference failed: {type(e).__name__}"}
