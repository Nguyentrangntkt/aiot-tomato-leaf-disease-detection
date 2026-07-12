"""Ham crop bbox voi padding cho pipeline detect va classify.
Padding giup crop khong bi cat mat vien la khi bbox detector hoi sat.
"""
from __future__ import annotations
import numpy as np


# padding_ratio bang khong phay mot nghia la mo rong moi canh theo muoi phan tram bbox.
def crop_with_padding(
    frame: np.ndarray,
    bbox,
    padding_ratio: float = 0.10,
) -> np.ndarray:


    h, w = frame.shape[:2]
    bw = bbox.x2 - bbox.x1
    bh = bbox.y2 - bbox.y1
    if bw <= 0 or bh <= 0:
        return np.zeros((0, 0, 3), dtype=frame.dtype)

    pad_x = int(round(bw * padding_ratio))
    pad_y = int(round(bh * padding_ratio))

    x1 = max(0, bbox.x1 - pad_x)
    y1 = max(0, bbox.y1 - pad_y)
    x2 = min(w, bbox.x2 + pad_x)
    y2 = min(h, bbox.y2 + pad_y)

    return frame[y1:y2, x1:x2]
