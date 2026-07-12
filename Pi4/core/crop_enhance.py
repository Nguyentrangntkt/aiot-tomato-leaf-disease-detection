"""Tien xu ly crop la bang HSV mask va contour.
Ham tighten_bbox_hsv cat lai vung la lon nhat de giam nen truoc khi phan loai.
"""
from __future__ import annotations
import cv2
import numpy as np


# Khoang HSV cua la gom xanh, vang va nau nhe de bao ca la benh.
LEAF_HSV_LOW  = np.array([8,  25, 30],  dtype=np.uint8)
LEAF_HSV_HIGH = np.array([100, 255, 240], dtype=np.uint8)


# Khoang HSV cua canh xanh dam duoc tru ra khoi mask la.
STEM_HSV_LOW  = np.array([35, 80, 30],  dtype=np.uint8)
STEM_HSV_HIGH = np.array([75, 255, 120], dtype=np.uint8)


# Tim contour la lon nhat trong ROI va crop sat lai voi padding nho.
def tighten_bbox_hsv(
    roi: np.ndarray,
    min_contour_area: int = 1500,
    padding_pixels: int = 10,
) -> np.ndarray:


    if roi is None or roi.size == 0:
        return roi

    H, W = roi.shape[:2]
    if H < 32 or W < 32:
        return roi

    # HSV tach mau la tot hon RGB khi anh thay doi do sang.
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)


    leaf_mask = cv2.inRange(hsv, LEAF_HSV_LOW, LEAF_HSV_HIGH)


    stem_mask = cv2.inRange(hsv, STEM_HSV_LOW, STEM_HSV_HIGH)
    leaf_mask = cv2.bitwise_and(leaf_mask, cv2.bitwise_not(stem_mask))


    # Close lap lo nho tren mat la, open loai nhieu diem nho.
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (12, 12))
    k_open  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    leaf_mask = cv2.morphologyEx(leaf_mask, cv2.MORPH_CLOSE, k_close)
    leaf_mask = cv2.morphologyEx(leaf_mask, cv2.MORPH_OPEN, k_open)


    contours, _ = cv2.findContours(
        leaf_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return roi


    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < min_contour_area:
        return roi


    x, y, w, h = cv2.boundingRect(largest)
    p = padding_pixels
    x1 = max(0, x - p)
    y1 = max(0, y - p)
    x2 = min(W, x + w + p)
    y2 = min(H, y + h + p)
    return roi[y1:y2, x1:x2]


# Ham tang chat luong crop de thu nghiem. Pipeline chinh hien khong bat mac dinh.
def enhance_crop(
    crop: np.ndarray,
    use_wb: bool = False,
    use_clahe: bool = True,
    use_saturation: bool = True,
    sat_factor: float = 1.25,
    clahe_clip: float = 2.0,
    target_size: int = 160,
) -> np.ndarray:


    if crop is None or crop.size == 0:
        return crop

    result = crop.copy()

    # White balance, CLAHE va saturation chi dung khi can bu anh thieu sang.
    if use_wb:
        result = _white_balance_lab(result)

    if use_clahe:
        result = _apply_clahe(result, clip_limit=clahe_clip)

    if use_saturation:
        result = _boost_saturation(result, factor=sat_factor)


    result = cv2.resize(result, (target_size, target_size))
    return result


def _white_balance_lab(crop: np.ndarray) -> np.ndarray:

    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    a = (a.astype(np.float32) - np.mean(a) + 128).clip(0, 255).astype(np.uint8)
    b = (b.astype(np.float32) - np.mean(b) + 128).clip(0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def _apply_clahe(crop: np.ndarray, clip_limit: float = 2.0) -> np.ndarray:

    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def _boost_saturation(crop: np.ndarray, factor: float = 1.25) -> np.ndarray:

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
