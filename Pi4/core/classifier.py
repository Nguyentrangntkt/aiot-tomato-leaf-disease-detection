"""Classifier stage mot cho Healthy va Diseased bang model Edge Impulse.
Input nhan crop BGR tu OpenCV va chuyen sang RGB truoc khi suy luan.
"""
from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass


@dataclass
class ClassifyResult:
    label: str
    confidence: float
    all_scores: dict
    status: str


class ClassifierEIM:

    # conf_threshold la nguong ket luan chac chan.
    # suspicious_threshold la nguong trung gian de danh dau ket qua chua chac.
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

        self.labels = info["model_parameters"].get("labels", ["Diseased", "Healthy"])
        print(f"[Classifier] loaded: {info['project']['name']} "
              f"(input {self.input_size}, labels={self.labels})")

    def classify(self, crop_bgr: np.ndarray) -> ClassifyResult:
        # Edge Impulse nhan anh RGB nen crop BGR tu OpenCV phai duoc chuyen mau.
        if crop_bgr is None or crop_bgr.size == 0:
            return ClassifyResult("unknown", 0.0, {}, "low_conf")

        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        features, _ = self.runner.get_features_from_image(rgb)
        res = self.runner.classify(features)
        scores = res.get("result", {}).get("classification", {})


        if not scores:
            return ClassifyResult("unknown", 0.0, {}, "low_conf")


        top_label, top_conf = max(scores.items(), key=lambda kv: kv[1])
        top_conf = float(top_conf)

        # Trang thai ket qua phu thuoc vao confidence cao nhat cua model.
        if top_conf >= self.conf_th:
            status = "confident"
        elif top_conf >= self.susp_th:
            status = "suspicious"
        else:
            status = "low_conf"

        return ClassifyResult(top_label, top_conf, dict(scores), status)

    def close(self):
        if self.runner is not None:
            self.runner.stop()
            self.runner = None
