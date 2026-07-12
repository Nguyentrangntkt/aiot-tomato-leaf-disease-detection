"""Classifier stage hai cho LeafMiner va EarlyBlight.
Model nay dung anh grayscale de tap trung vao vet benh va giam anh huong mau sac.
"""
from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass


@dataclass
class DiseaseResult:
    label: str
    confidence: float
    all_scores: dict
    status: str


class DiseaseClassifierEIM:

    # Nguong stage hai thap hon stage mot vi crop benh co the nho va kem sang.
    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.55,
        suspicious_threshold: float = 0.50,
    ):
        from edge_impulse_linux.image import ImageImpulseRunner
        self.conf_th = conf_threshold
        self.susp_th = suspicious_threshold
        self.runner = ImageImpulseRunner(model_path)
        info = self.runner.init()
        self.input_size = info["model_parameters"]["image_input_width"]
        self.labels = info["model_parameters"].get("labels", ["EarlyBlight", "LeafMiner"])
        print(f"[DiseaseClassifier-GRAY] loaded: {info['project']['name']} "
              f"(input {self.input_size}, labels={self.labels})")

    def classify(self, crop_bgr: np.ndarray) -> DiseaseResult:
        # Chuyen BGR sang gray de giong tap train cua model benh.
        if crop_bgr is None or crop_bgr.size == 0:
            return DiseaseResult("unknown", 0.0, {}, "low_conf")


        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)


        # SDK yeu cau ba kenh nen lap lai anh gray thanh ba kenh giong nhau.
        gray_3ch = cv2.merge([gray, gray, gray])

        features, _ = self.runner.get_features_from_image(gray_3ch)
        res = self.runner.classify(features)
        scores = res.get("result", {}).get("classification", {})

        if not scores:
            return DiseaseResult("unknown", 0.0, {}, "low_conf")

        top_label, top_conf = max(scores.items(), key=lambda kv: kv[1])
        top_label = top_label.replace("_", "")
        top_conf = float(top_conf)

        if top_conf >= self.conf_th:
            status = "confident"
        elif top_conf >= self.susp_th:
            status = "suspicious"
        else:
            status = "low_conf"

        return DiseaseResult(top_label, top_conf, dict(scores), status)

    def close(self):
        if self.runner is not None:
            self.runner.stop()
            self.runner = None
