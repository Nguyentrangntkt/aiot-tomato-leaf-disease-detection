"""Entrypoint chay mot lan chup va phan loai la ca chua.
File nay duoc pi4_brain goi khi ESP32 bao da den vi tri chup anh.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np


# Them thu muc goc de import cac module trong core khi chay tu scripts.
REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

from core.camera import Camera
from core.detector import DetectorEIM
from core.classifier import ClassifierEIM
from core.disease_classifier import DiseaseClassifierEIM
from core.capture_mode import run_capture_analysis


# Duong dan model mac dinh. Co the thay doi bang tham so command line.
DEFAULT_DETECTOR    = str(REPO_DIR / "models" / "detector.eim")
DEFAULT_CLASSIFIER  = str(REPO_DIR / "models" / "classifier.eim")
DEFAULT_DISEASE_CLS = str(REPO_DIR / "models" / "disease_classifier.eim")
DEFAULT_RESULT_DIR  = str(REPO_DIR / "ai_results")


# Thong so chup anh mot vi tri. Burst frame giup chon frame net hon.
BURST_FRAMES     = 8
CAPTURE_SEC      = 1.5
WARMUP_S         = 1.5
CAM_WIDTH        = 1920
CAM_HEIGHT       = 1080


# Nguong confidence cho detector va hai classifier.
# Suspicious la nguong trung gian de tranh ket luan qua chac khi model yeu.
DET_CONF     = 0.40
CLS_CONF     = 0.55
CLS_SUSP     = 0.50
DISEASE_CONF = 0.45
DISEASE_SUSP = 0.35


# Mot la phai duoc phat hien it nhat hai lan trong burst frame moi duoc giu lai.
MIN_DETECT_PER_CLUSTER = 2


# Mau ve bbox theo dinh dang BGR cua OpenCV.
LABEL_COLORS = {
    "Healthy":      (60, 200, 60),
    "LeafMiner":    (180, 80, 220),
    "EarlyBlight":  (40, 40, 220),
    "Diseased":     (40, 40, 220),
    "Diseased (?)": (40, 100, 200),
    "LowConf":      (160, 160, 160),
    "Uncertain":    (40, 165, 240),
}


def draw_result(frame: np.ndarray, leaves: list[dict]) -> np.ndarray:
    # Ve bbox va nhan len anh ket qua de luu khi phat hien benh.
    out = frame.copy()
    for lf in leaves:
        x1, y1, x2, y2 = lf["bbox"]
        label = lf["label"]
        conf  = lf["confidence"]
        color = LABEL_COLORS.get(label, (200, 100, 200))

        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        txt = f"{label} {conf*100:.0f}%"
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        yt = max(th + 4, y1)
        cv2.rectangle(out, (x1, yt - th - 4), (x1 + tw + 4, yt), color, -1)
        cv2.putText(out, txt, (x1 + 2, yt - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def reports_to_output(reports, position_cm: float) -> tuple[list[dict], dict]:
    # Doi report noi bo thanh JSON dung cho pi4_brain va app.
    leaves = []
    summary: dict[str, int] = {}
    disease_leaf = None

    for r in reports:
        label = r.final_label

        if r.stage2 is not None and label in ("LeafMiner", "EarlyBlight"):
            conf = r.stage2.avg_conf
        else:
            conf = r.stage1.avg_conf

        bb = r.bbox
        leaf = {
            "label": label,
            "confidence": round(conf, 4),
            "bbox": [bb.x1, bb.y1, bb.x2, bb.y2],
            "n_detections": r.n_detections,
            "vote_ratio": r.stage1.vote_ratio,
        }
        leaves.append(leaf)
        summary[label] = summary.get(label, 0) + 1

        if label not in ("Healthy", "Uncertain", "LowConf"):
            if disease_leaf is None or conf > disease_leaf["confidence"]:
                disease_leaf = leaf

    if not leaves:
        output = {
            "has_disease": False,
            "final_label": "Uncertain",
            "confidence": 0.0,
            "leaf_count": 0,
            "scan_status": "uncertain",
            "summary": {},
            "leaves": [],
            "position_cm": position_cm,
        }
        return leaves, output

    disease_labels = {
        lb: cnt for lb, cnt in summary.items()
        if lb not in ("Healthy", "Uncertain", "LowConf")
    }
    has_disease = bool(disease_labels)

    if has_disease and len(disease_labels) == 1:
        display_label = list(disease_labels.keys())[0]
        scan_status = "diseased"
        confidence = disease_leaf["confidence"]
    elif has_disease:
        display_label = ", ".join(f"{lb} ({cnt})" for lb, cnt in disease_labels.items())
        scan_status = "diseased"
        confidence = disease_leaf["confidence"]
    elif all(leaf["label"] == "Healthy" for leaf in leaves):
        display_label = "Healthy"
        scan_status = "healthy"
        confidence = max(leaf["confidence"] for leaf in leaves)
    else:
        display_label = "Uncertain"
        scan_status = "uncertain"
        confidence = max(leaf["confidence"] for leaf in leaves)

    output = {
        "has_disease": has_disease,
        "final_label": display_label,
        "confidence": confidence,
        "leaf_count": len(leaves),
        "scan_status": scan_status,
        "summary": summary,
        "leaves": leaves,
        "position_cm": position_cm,
    }
    return leaves, output


def main():
    # single shot la che do chup va phan loai mot vi tri tren ray truot.
    ap = argparse.ArgumentParser()
    ap.add_argument("--single-shot", action="store_true", required=True)
    ap.add_argument("--position",    type=float, default=0.0)
    ap.add_argument("--json-out",    type=str,   default="")
    ap.add_argument("--detector",    default=DEFAULT_DETECTOR)
    ap.add_argument("--classifier",  default=DEFAULT_CLASSIFIER)
    ap.add_argument("--disease-classifier", default=DEFAULT_DISEASE_CLS)
    ap.add_argument("--result-dir",  default=DEFAULT_RESULT_DIR)
    ap.add_argument("--burst",       type=int, default=BURST_FRAMES)
    args = ap.parse_args()

    result_dir = Path(args.result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")


    # Load ba model theo thu tu detect, phan loai khoe benh, phan loai loai benh.
    detector = DetectorEIM(args.detector, conf_threshold=DET_CONF)
    classifier = ClassifierEIM(args.classifier, conf_threshold=CLS_CONF,
                               suspicious_threshold=CLS_SUSP)

    disease_cls = None
    if Path(args.disease_classifier).exists():
        try:
            disease_cls = DiseaseClassifierEIM(args.disease_classifier,
                                               conf_threshold=DISEASE_CONF,
                                               suspicious_threshold=DISEASE_SUSP)
        except Exception as e:
            print(f"[Pipeline] WARN disease_classifier: {e}", file=sys.stderr)


    # Mo camera do phan giai cao roi warmup truoc khi chup burst frame.
    cam = Camera(width=CAM_WIDTH, height=CAM_HEIGHT, fps=15)
    cam.start()
    time.sleep(WARMUP_S)


    # Chay pipeline chinh gom capture, detect, cluster, vote va classify.
    rep_frame, reports = run_capture_analysis(
        cam=cam,
        detector=detector,
        classifier=classifier,
        disease_classifier=disease_cls,
        enhancer=None,
        use_enhance=False,
        use_tighten=True,
        use_enhance_crop=False,
        use_lighting_norm=False,
        num_frames=args.burst,
        capture_sec=CAPTURE_SEC,
        nms_iou=0.5,
        min_detect_per_cluster=MIN_DETECT_PER_CLUSTER,
    )
    cam.stop()


    if rep_frame is None:
        _finish(detector, classifier, disease_cls,
                {"has_disease": False, "final_label": "unknown", "confidence": 0.0,
                 "scan_status": "error", "note": "Camera không chụp được frame",
                 "leaf_count": 0, "summary": {}, "leaves": [],
                 "position_cm": args.position},
                args.json_out, rc=1)
        return


    # Luon luu anh goc de doi chieu khi can debug ket qua.
    raw_path = result_dir / f"raw_{ts}_pos{args.position:.1f}.jpg"
    cv2.imwrite(str(raw_path), rep_frame, [cv2.IMWRITE_JPEG_QUALITY, 92])


    leaves, output = reports_to_output(reports, args.position)
    output["raw_image_path"] = str(raw_path)
    output["timestamp"] = ts


    # Chi luu anh annotated khi co benh de Cloudinary va app khong bi day anh khong can thiet.
    if output["has_disease"]:
        ann_path = result_dir / f"annotated_{ts}_pos{args.position:.1f}.jpg"
        cv2.imwrite(str(ann_path), draw_result(rep_frame, leaves),
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        output["result_image_path"] = str(ann_path)


    _finish(detector, classifier, disease_cls, output, args.json_out, rc=0)


def _finish(detector, classifier, disease_cls, output: dict, json_out: str, rc: int = 0):
    # Dong model va in JSON ra stdout de pi4_brain doc khi can fallback.
    detector.close()
    classifier.close()
    if disease_cls is not None:
        disease_cls.close()

    txt = json.dumps(output, indent=2, ensure_ascii=False)
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(txt, encoding="utf-8")

    print(txt, flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
