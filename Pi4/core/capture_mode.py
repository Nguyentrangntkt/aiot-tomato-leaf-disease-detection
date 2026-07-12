"""Capture mode cho pipeline phan loai la ca chua.
Module nay chup nhieu frame, gom bbox trung nhau, chon frame sac net va vote ket qua.
"""
from __future__ import annotations
import time
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Callable

from core.detector import BBox
from core.crop_enhance import tighten_bbox_hsv, enhance_crop
from core.preprocess import crop_with_padding
from core.hsv_filter import HSVFilter


# So frame va thoi gian chup dung de giam anh huong cua rung va anh mo.
DEFAULT_NUM_FRAMES   = 30
DEFAULT_CAPTURE_SEC  = 2.0
DEFAULT_NMS_IOU      = 0.5
DEFAULT_MIN_DETECT   = 3
DEFAULT_NUM_CLASSIFY = 5
DEFAULT_VOTE_RATIO   = 0.6


# Nguong stage mot cho Healthy va Diseased cao hon vi day la buoc quyet dinh co benh.
# Nguong stage hai thap hon mot chut vi anh benh co the bi che khuat hoac thieu sang.
DEFAULT_CLS_CONF_FILTER     = 0.55
DEFAULT_CLS_AVG_CONF        = 0.60
DEFAULT_DISEASE_CONF_FILTER = 0.40
DEFAULT_DISEASE_AVG_CONF    = 0.45


@dataclass
class FrameDet:
    frame_idx: int
    bbox: BBox
    sharpness: float = 0.0


@dataclass
class BBoxCluster:
    detections: list[FrameDet] = field(default_factory=list)

    @property
    def n_detections(self) -> int:
        return len(self.detections)

    def avg_bbox(self) -> BBox:
        xs1 = [d.bbox.x1 for d in self.detections]
        ys1 = [d.bbox.y1 for d in self.detections]
        xs2 = [d.bbox.x2 for d in self.detections]
        ys2 = [d.bbox.y2 for d in self.detections]
        conf = sum(d.bbox.confidence for d in self.detections) / len(self.detections)
        return BBox(
            x1=int(sum(xs1) / len(xs1)),
            y1=int(sum(ys1) / len(ys1)),
            x2=int(sum(xs2) / len(xs2)),
            y2=int(sum(ys2) / len(ys2)),
            confidence=conf,
        )

    def best_frames(self, k: int = 5) -> list[FrameDet]:
        return sorted(self.detections, key=lambda d: -d.sharpness)[:k]


@dataclass
class ClassifyResult:
    label: str
    avg_conf: float
    vote_ratio: float
    all_confs: list[float]
    all_labels: list[str]
    final_status: str


@dataclass
class ClusterReport:
    bbox: BBox
    n_detections: int
    stage1: ClassifyResult
    stage2: ClassifyResult | None
    final_label: str


# Tinh do chong lap cua hai bbox de gom cac phat hien cua cung mot la.
def bbox_iou(a: BBox, b: BBox) -> float:
    x1 = max(a.x1, b.x1); y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2); y2 = min(a.y2, b.y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


# Gom bbox theo IoU de mot la xuat hien o nhieu frame chi tinh la mot doi tuong.
def cluster_bboxes(all_dets, iou_thresh=DEFAULT_NMS_IOU):
    if not all_dets:
        return []
    sorted_dets = sorted(all_dets, key=lambda d: -d.bbox.confidence)
    clusters = []
    used = [False] * len(sorted_dets)
    for i, det_i in enumerate(sorted_dets):
        if used[i]:
            continue
        cluster = BBoxCluster(detections=[det_i])
        used[i] = True
        for j in range(i + 1, len(sorted_dets)):
            if used[j]:
                continue
            if bbox_iou(det_i.bbox, sorted_dets[j].bbox) >= iou_thresh:
                cluster.detections.append(sorted_dets[j])
                used[j] = True
        clusters.append(cluster)
    return clusters


# Do net duoc tinh bang phuong sai Laplacian de chon frame tot nhat.
def crop_sharpness(crop):
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# Hop nhat nhieu lan phan loai bang vote ratio va confidence trung binh.
def _aggregate_two_class(confs, labels, neg_label, pos_label,
                          vote_thresh, avg_conf_thresh):
    if not labels:
        return ClassifyResult("unknown", 0.0, 0.0, [], [], "Uncertain")
    pos_count = sum(1 for l in labels if l == pos_label)
    neg_count = sum(1 for l in labels if l == neg_label)
    total = len(labels)
    vote_pos = pos_count / total
    vote_neg = neg_count / total
    avg_pos = (sum(c for c, l in zip(confs, labels) if l == pos_label) / pos_count
               if pos_count > 0 else 0.0)
    avg_neg = (sum(c for c, l in zip(confs, labels) if l == neg_label) / neg_count
               if neg_count > 0 else 0.0)
    if vote_pos >= vote_thresh and avg_pos >= avg_conf_thresh:
        return ClassifyResult(pos_label, avg_pos, vote_pos, confs, labels, pos_label)
    if vote_neg >= vote_thresh and avg_neg >= avg_conf_thresh:
        return ClassifyResult(neg_label, avg_neg, vote_neg, confs, labels, neg_label)
    if pos_count >= neg_count:
        return ClassifyResult(pos_label, avg_pos, vote_pos, confs, labels, "Uncertain")
    return ClassifyResult(neg_label, avg_neg, vote_neg, confs, labels, "Uncertain")


# Stage mot phan loai Healthy va Diseased.
# Dung nam crop sac net nhat, co the tighten bang HSV truoc khi dua vao model.
def classify_stage1_5frames(
    classifier,
    frames,
    cluster,
    target_labels,
    use_tighten: bool = True,
    use_enhance_crop: bool = False,
    use_lighting_norm: bool = False,
    hsv_filter=None,
    conf_filter: float = DEFAULT_CLS_CONF_FILTER,
    vote_thresh: float = DEFAULT_VOTE_RATIO,
    avg_conf_thresh: float = DEFAULT_CLS_AVG_CONF,
    debug_saver=None,
    cluster_idx: int = 0,
):
    neg_label, pos_label = target_labels
    best_dets = cluster.best_frames(k=DEFAULT_NUM_CLASSIFY)
    confs, labels = [], []

    for fi, det in enumerate(best_dets):
        frame = frames[det.frame_idx]
        # Padding muoi phan tram giup crop khong cat mat vien la.
        raw_crop = crop_with_padding(frame, det.bbox, padding_ratio=0.10)
        if raw_crop.size == 0 or raw_crop.shape[0] < 32 or raw_crop.shape[1] < 32:
            continue

        cls_crop = raw_crop.copy()
        if use_tighten:
            # Tighten HSV chi lay vung la lon nhat trong bbox de giam nen va canh.
            tightened = tighten_bbox_hsv(cls_crop)
            if tightened.size > 0:
                cls_crop = tightened

        if hsv_filter is not None:
            # Loc crop khong du mau la hoac co qua nhieu mau da tay.
            hres = hsv_filter.check(cls_crop)
            if not hres.passed:
                continue


        if use_enhance_crop:
            cls_crop = enhance_crop(cls_crop)

        cres = classifier.classify(cls_crop)

        if debug_saver and debug_saver.session_dir is not None:
            debug_saver.start_detection(cluster_idx * 100 + fi)
            debug_saver.save_step("02_bbox_raw", raw_crop)
            debug_saver.save_step("03_cls_crop_final", cls_crop)
            debug_saver.save_result(f"05_stage1_frame{fi}", {
                "label": cres.label,
                "confidence": cres.confidence,
                "all_scores": cres.all_scores,
                "passed_filter": cres.confidence >= conf_filter,
            })

        if cres.confidence < conf_filter:
            continue
        confs.append(cres.confidence)
        labels.append(cres.label)

    return _aggregate_two_class(confs, labels, neg_label, pos_label,
                                 vote_thresh, avg_conf_thresh)


# Stage hai phan loai LeafMiner va EarlyBlight.
# Giu raw crop co padding vi model benh duoc train theo crop goc.
def classify_stage2_5frames(
    disease_classifier,
    frames,
    cluster,
    target_labels,
    conf_filter: float = DEFAULT_DISEASE_CONF_FILTER,
    vote_thresh: float = DEFAULT_VOTE_RATIO,
    avg_conf_thresh: float = DEFAULT_DISEASE_AVG_CONF,
    debug_saver=None,
    cluster_idx: int = 0,
):

    neg_label, pos_label = target_labels
    best_dets = cluster.best_frames(k=DEFAULT_NUM_CLASSIFY)
    confs, labels = [], []

    for fi, det in enumerate(best_dets):
        frame = frames[det.frame_idx]
        raw_crop = crop_with_padding(frame, det.bbox, padding_ratio=0.10)
        if raw_crop.size == 0 or raw_crop.shape[0] < 32 or raw_crop.shape[1] < 32:
            continue


        cres = disease_classifier.classify(raw_crop)

        if debug_saver and debug_saver.session_dir is not None:
            debug_saver.start_detection(cluster_idx * 100 + 50 + fi)
            gray = cv2.cvtColor(raw_crop, cv2.COLOR_BGR2GRAY)
            gray_96 = cv2.resize(gray, (disease_classifier.input_size,
                                         disease_classifier.input_size))
            debug_saver.save_classifier_input("06a_disease_input_gray", gray_96)
            debug_saver.save_result(f"06b_stage2_frame{fi}", {
                "label": cres.label,
                "confidence": cres.confidence,
                "all_scores": cres.all_scores,
                "from": "RAW_BBOX (no tighten/enhance)",
                "passed_filter": cres.confidence >= conf_filter,
            })

        if cres.confidence < conf_filter:
            continue
        confs.append(cres.confidence)
        labels.append(cres.label)

    return _aggregate_two_class(confs, labels, neg_label, pos_label,
                                 vote_thresh, avg_conf_thresh)


# Ham chinh cua capture mode gom cac buoc chup anh, detect, cluster, classify va tao report.
def run_capture_analysis(
    cam,
    detector,
    classifier,
    disease_classifier=None,
    enhancer=None,
    use_enhance: bool = False,
    use_tighten: bool = True,
    use_enhance_crop: bool = False,
    use_lighting_norm: bool = False,
    num_frames: int = DEFAULT_NUM_FRAMES,
    capture_sec: float = DEFAULT_CAPTURE_SEC,
    nms_iou: float = DEFAULT_NMS_IOU,
    min_detect_per_cluster: int = DEFAULT_MIN_DETECT,
    stage1_labels=("Healthy", "Diseased"),
    stage2_labels=("LeafMiner", "EarlyBlight"),
    progress_cb=None,
    debug_saver=None,
):

    # Chup burst frame trong khoang capture_sec.
    if progress_cb: progress_cb("capturing", 0, num_frames)
    frames = []
    frame_interval = capture_sec / num_frames
    t_start = time.time()
    for i in range(num_frames):
        t_target = t_start + i * frame_interval
        wait = t_target - time.time()
        if wait > 0:
            time.sleep(wait)
        f = cam.read()
        if f is None:
            continue
        frames.append(f)
        if progress_cb: progress_cb("capturing", i + 1, num_frames)
    if not frames:
        return None, []


    if debug_saver is not None:
        debug_saver.start_session(prefix="capture")
        debug_saver.save_frame_raw(frames[0])
        if len(frames) >= 3:
            debug_saver._save_img("00_frame_mid.jpg", frames[len(frames) // 2],
                                  where=debug_saver.session_dir)
            debug_saver._save_img("00_frame_last.jpg", frames[-1],
                                  where=debug_saver.session_dir)


    # Detector chay tren anh resize ve 640 roi map bbox ve kich thuoc goc.
    if progress_cb: progress_cb("detecting", 0, len(frames))
    all_dets = []
    for idx, frame in enumerate(frames):
        det_input = enhancer.enhance(frame) if (use_enhance and enhancer) else frame
        H0, W0 = det_input.shape[:2]
        resized = cv2.resize(det_input, (640, 640))
        bboxes = detector.detect(resized)
        sx, sy = W0 / 640.0, H0 / 640.0
        for bb in bboxes:
            bb.x1 = int(bb.x1 * sx); bb.x2 = int(bb.x2 * sx)
            bb.y1 = int(bb.y1 * sy); bb.y2 = int(bb.y2 * sy)
            crop = frame[bb.y1:bb.y2, bb.x1:bb.x2]
            if crop.size == 0:
                continue
            sharpness = crop_sharpness(crop)
            all_dets.append(FrameDet(frame_idx=idx, bbox=bb, sharpness=sharpness))
        if progress_cb: progress_cb("detecting", idx + 1, len(frames))


    # Chi giu cluster co du so lan phat hien toi thieu de giam false positive.
    if progress_cb: progress_cb("clustering", 0, 1)
    clusters = cluster_bboxes(all_dets, iou_thresh=nms_iou)
    clusters = [c for c in clusters if c.n_detections >= min_detect_per_cluster]
    if progress_cb: progress_cb("clustering", 1, 1)


    hsv = HSVFilter()
    reports = []
    # Moi cluster dai dien cho mot la sau khi gom cac bbox qua nhieu frame.
    for ci, cluster in enumerate(clusters):
        if progress_cb: progress_cb("classifying", ci, len(clusters))


        s1 = classify_stage1_5frames(
            classifier, frames, cluster, stage1_labels,
            use_tighten=use_tighten,
            use_enhance_crop=use_enhance_crop,
            use_lighting_norm=use_lighting_norm,
            hsv_filter=hsv,
            debug_saver=debug_saver,
            cluster_idx=ci,
        )


        s2 = None
        # Chi chay model benh khi stage mot xac dinh la benh.
        if s1.final_status == "Diseased" and disease_classifier is not None:
            s2 = classify_stage2_5frames(
                disease_classifier, frames, cluster, stage2_labels,
                debug_saver=debug_saver,
                cluster_idx=ci,
            )


        if s1.final_status == "Healthy":
            final_label = "Healthy"
        elif s1.final_status == "Diseased":
            if s2 is None:
                final_label = "Diseased"
            elif s2.final_status in stage2_labels:
                final_label = s2.final_status
            else:
                final_label = "Diseased (?)"
        else:
            final_label = "Uncertain"

        reports.append(ClusterReport(
            bbox=cluster.avg_bbox(),
            n_detections=cluster.n_detections,
            stage1=s1,
            stage2=s2,
            final_label=final_label,
        ))
    if progress_cb: progress_cb("classifying", len(clusters), len(clusters))


    if all_dets:
        # Chon frame dai dien co tong do net cao nhat de luu anh ket qua.
        rep_frame_idx = max(range(len(frames)),
                            key=lambda i: sum(d.sharpness for d in all_dets if d.frame_idx == i))
        rep_frame = frames[rep_frame_idx]
    else:
        rep_frame = frames[len(frames) // 2]


    if debug_saver is not None and debug_saver.session_dir is not None:
        meta = {
            "mode": "capture",
            "n_frames": len(frames),
            "n_detections": len(all_dets),
            "n_clusters": len(clusters),
            "pipeline_options": {
                "tighten": use_tighten,
                "enhance_crop": use_enhance_crop,
                "use_enhance_frame": use_enhance,
            },
            "reports": [
                {
                    "final_label": r.final_label,
                    "stage1_label": r.stage1.label,
                    "stage1_avg": r.stage1.avg_conf,
                    "stage1_n": len(r.stage1.all_confs),
                    "stage2_label": r.stage2.label if r.stage2 else None,
                    "stage2_avg": r.stage2.avg_conf if r.stage2 else None,
                    "stage2_n": len(r.stage2.all_confs) if r.stage2 else 0,
                } for r in reports
            ],
        }
        session_path = debug_saver.finalize(meta)
        print(f"[Capture-Debug] Saved -> {session_path}")

    if progress_cb: progress_cb("done", 1, 1)
    return rep_frame, reports
