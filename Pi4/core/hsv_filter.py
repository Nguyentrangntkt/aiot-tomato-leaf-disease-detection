"""HSV filter dung de loai crop khong phai la hoac co qua nhieu mau da tay.
Buoc nay giup giam false positive truoc khi classifier stage mot chay.
"""
from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass


@dataclass
class HSVResult:
    passed: bool
    leaf_ratio: float
    skin_ratio: float
    reason: str


class HSVFilter:

    def __init__(
        self,
        # Khoang HSV la duoc mo rong de bao ca la xanh, vang va nau nhe.
        leaf_h: tuple[int, int] = (8, 100),
        leaf_s: tuple[int, int] = (25, 255),
        leaf_v: tuple[int, int] = (30, 240),

        # Khoang mau da tay dung de loai crop bi dinh tay nguoi.
        skin_h: tuple[int, int] = (0, 25),
        skin_s: tuple[int, int] = (30, 200),
        skin_v: tuple[int, int] = (80, 240),

        # Crop phai co it nhat bon muoi phan tram pixel giong la.
        # Neu mau da tay qua ba muoi phan tram thi loai crop.
        min_leaf_ratio: float = 0.40,
        max_skin_ratio: float = 0.30,
    ):
        self.leaf_low = np.array([leaf_h[0], leaf_s[0], leaf_v[0]], dtype=np.uint8)
        self.leaf_high = np.array([leaf_h[1], leaf_s[1], leaf_v[1]], dtype=np.uint8)
        self.skin_low = np.array([skin_h[0], skin_s[0], skin_v[0]], dtype=np.uint8)
        self.skin_high = np.array([skin_h[1], skin_s[1], skin_v[1]], dtype=np.uint8)
        self.min_leaf = min_leaf_ratio
        self.max_skin = max_skin_ratio

    def check(self, crop_bgr: np.ndarray) -> HSVResult:
        if crop_bgr is None or crop_bgr.size == 0:
            return HSVResult(False, 0.0, 0.0, "empty")

        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        total = hsv.shape[0] * hsv.shape[1]

        leaf_mask = cv2.inRange(hsv, self.leaf_low, self.leaf_high)
        skin_mask = cv2.inRange(hsv, self.skin_low, self.skin_high)

        # Ti le pixel duoc dung de quyet dinh crop co dang tin hay khong.
        leaf_ratio = float(np.count_nonzero(leaf_mask)) / total
        skin_ratio = float(np.count_nonzero(skin_mask)) / total

        if leaf_ratio < self.min_leaf:
            return HSVResult(False, leaf_ratio, skin_ratio, "not_enough_leaf")
        if skin_ratio > self.max_skin:
            return HSVResult(False, leaf_ratio, skin_ratio, "too_much_skin")
        return HSVResult(True, leaf_ratio, skin_ratio, "ok")
