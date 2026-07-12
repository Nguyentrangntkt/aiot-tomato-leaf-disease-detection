"""Detector la bang model Edge Impulse dang object detection.
BBox tu anh input cua model duoc map nguoc ve toa do anh goc.
"""
from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass
from typing import List


@dataclass
class BBox:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float

    @property
    def width(self) -> int: return self.x2 - self.x1
    @property
    def height(self) -> int: return self.y2 - self.y1
    @property
    def area(self) -> int: return self.width * self.height


class DetectorEIM:

    # conf_threshold loai bbox co confidence thap.
    # max_detections gioi han so bbox tra ve de tranh qua tai pipeline.
    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.40,
        max_detections: int = 20,
    ):
        from edge_impulse_linux.image import ImageImpulseRunner
        self.model_path = model_path
        self.conf_th = conf_threshold
        self.max_det = max_detections

        self.runner = ImageImpulseRunner(model_path)
        info = self.runner.init()
        self.input_size = info["model_parameters"]["image_input_width"]
        print(f"[Detector] loaded: {info['project']['name']} "
              f"(input {self.input_size}x{self.input_size})")

    def detect(self, frame_bgr: np.ndarray) -> List[BBox]:
        # Model Edge Impulse dung anh vuong nen can tinh scale va crop offset.
        H, W = frame_bgr.shape[:2]
        S = self.input_size


        # SDK nhan RGB trong khi OpenCV doc anh theo BGR.
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)


        scale = S / min(H, W)

        scaled_w = W * scale
        scaled_h = H * scale

        crop_offset_x = (scaled_w - S) / 2.0
        crop_offset_y = (scaled_h - S) / 2.0


        features, cropped = self.runner.get_features_from_image(rgb)
        res = self.runner.classify(features)

        bboxes: List[BBox] = []
        for bb in res.get("result", {}).get("bounding_boxes", []):
            conf = float(bb.get("value", 0.0))
            if conf < self.conf_th:
                continue


            x_in_crop = bb["x"]
            y_in_crop = bb["y"]
            w_in_crop = bb["width"]
            h_in_crop = bb["height"]


            # Cong offset va chia scale de doi bbox tu anh crop ve anh goc.
            x_in_scaled = x_in_crop + crop_offset_x
            y_in_scaled = y_in_crop + crop_offset_y


            x1 = int(x_in_scaled / scale)
            y1 = int(y_in_scaled / scale)
            x2 = int((x_in_scaled + w_in_crop) / scale)
            y2 = int((y_in_scaled + h_in_crop) / scale)


            # Clip bbox de khong vuot bien anh goc.
            x1 = max(0, min(x1, W - 1))
            y1 = max(0, min(y1, H - 1))
            x2 = max(0, min(x2, W - 1))
            y2 = max(0, min(y2, H - 1))
            if x2 - x1 < 1 or y2 - y1 < 1:
                continue
            bboxes.append(BBox(x1, y1, x2, y2, conf))


        bboxes.sort(key=lambda b: -b.confidence)
        return bboxes[: self.max_det]

    def close(self):
        if self.runner is not None:
            self.runner.stop()
            self.runner = None
