"""Camera capture cho Raspberry Pi va OpenCV fallback.
Module nay cau hinh do phan giai cao, autofocus va warmup truoc khi chup.
"""
from __future__ import annotations
import time
import cv2
import numpy as np


class Camera:

    # width height fps la thong so anh dau vao cho detector.
    # af_mode uu tien continuous de camera tu lay net khi khoang cach la thay doi.
    # manual_lens_position chi dung khi can khoa net thu cong.
    # af_window_ratio gioi han vung lay net o giua khung hinh de tap trung vao la.
    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        fps: int = 15,
        device_index: int = 0,
        warmup_seconds: float = 2.0,

        af_mode: str = "continuous",
        manual_lens_position: float = 5.0,

        af_window_ratio: float = 0.4,

    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.device_index = device_index
        self.warmup = warmup_seconds
        self.af_mode = af_mode
        self.manual_lens_position = manual_lens_position
        self.af_window_ratio = float(af_window_ratio)
        self.backend = None
        self._handle = None

    def start(self):
        # Uu tien Picamera2 tren Raspberry Pi. Neu khong co thi dung OpenCV fallback.
        try:
            from picamera2 import Picamera2
            self._handle = Picamera2()

            # RGB888 cua Picamera2 dang duoc giu nguyen de khop voi pipeline OpenCV.
            cfg = self._handle.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"},
                controls={"FrameRate": float(self.fps)},
            )
            self._handle.configure(cfg)


            # Cac thong so nay giup anh on dinh hon khi chup trong nha kinh hoac trong phong.
            base_controls = {
                "AeEnable": True,
                "AwbEnable": True,
                "AwbMode": 0,
                "AeExposureMode": 0,
                "Brightness": 0.0,
                "Contrast": 1.1,
                "Saturation": 1.0,
                "Sharpness": 1.2,
            }


            try:
                from libcamera import controls as libcam_controls


                # Toa do AF window tinh theo kich thuoc sensor cua Pi Camera v3.
                sensor_w, sensor_h = 4608, 2592
                ratio = max(0.1, min(1.0, self.af_window_ratio))
                win_w = int(sensor_w * ratio)
                win_h = int(sensor_h * ratio)
                win_x = (sensor_w - win_w) // 2
                win_y = (sensor_h - win_h) // 2
                af_window_rect = (win_x, win_y, win_w, win_h)

                if self.af_mode == "continuous":
                    base_controls["AfMode"] = libcam_controls.AfModeEnum.Continuous
                    base_controls["AfSpeed"] = libcam_controls.AfSpeedEnum.Fast
                    base_controls["AfRange"] = libcam_controls.AfRangeEnum.Macro
                    base_controls["AfMetering"] = libcam_controls.AfMeteringEnum.Windows
                    base_controls["AfWindows"] = [af_window_rect]
                    print(f"[Camera] AF mode: CONTINUOUS (macro, fast, "
                          f"window={int(ratio*100)}% giữa)")
                elif self.af_mode == "auto":
                    base_controls["AfMode"] = libcam_controls.AfModeEnum.Auto
                    base_controls["AfRange"] = libcam_controls.AfRangeEnum.Macro
                    base_controls["AfMetering"] = libcam_controls.AfMeteringEnum.Windows
                    base_controls["AfWindows"] = [af_window_rect]
                    print(f"[Camera] AF mode: AUTO (1-shot, window={int(ratio*100)}% giữa)")
                elif self.af_mode == "manual":
                    base_controls["AfMode"] = libcam_controls.AfModeEnum.Manual
                    base_controls["LensPosition"] = float(self.manual_lens_position)
                    dist_cm = 100.0 / max(self.manual_lens_position, 0.01)
                    print(f"[Camera] AF mode: MANUAL "
                          f"(lens={self.manual_lens_position} ~ {dist_cm:.0f}cm)")
            except ImportError:

                print("[Camera] WARN: libcamera.controls không có -> không set được AF")

            self._handle.set_controls(base_controls)
            self._handle.start()


            if self.af_mode == "auto":
                try:
                    self._handle.autofocus_cycle()
                    print("[Camera] AF cycle hoàn tất")
                except Exception as e:
                    print(f"[Camera] AF cycle failed: {e}")

            self.backend = "picamera2"
            print(f"[Camera] picamera2 started @ {self.width}x{self.height} {self.fps}fps")
        except ImportError:
            # Fallback cho webcam hoac moi truong khong co Picamera2.
            self._handle = cv2.VideoCapture(self.device_index)
            self._handle.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._handle.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._handle.set(cv2.CAP_PROP_FPS, self.fps)

            self._handle.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
            if not self._handle.isOpened():
                raise RuntimeError(f"Không mở được camera index {self.device_index}")
            self.backend = "opencv"
            print(f"[Camera] OpenCV VideoCapture started @ "
                  f"{int(self._handle.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                  f"{int(self._handle.get(cv2.CAP_PROP_FRAME_HEIGHT))}")


        # Bo qua cac frame dau de exposure va white balance on dinh.
        print(f"[Camera] warmup {self.warmup}s...")
        t0 = time.time()
        while time.time() - t0 < self.warmup:
            self.read()
        print("[Camera] ready")

    def read(self) -> np.ndarray | None:
        if self.backend == "picamera2":
            # Tra ve frame dang BGR de cac buoc xu ly anh dung OpenCV truc tiep.
            return self._handle.capture_array()
        elif self.backend == "opencv":
            ok, frame = self._handle.read()
            return frame if ok else None
        return None

    def trigger_autofocus(self) -> bool:
        # Ham nay chi co y nghia voi Pi Camera co ho tro autofocus.
        if self.backend != "picamera2":
            return False
        try:

            success = self._handle.autofocus_cycle()
            print(f"[Camera] Manual AF cycle: {'OK' if success else 'FAILED'}")
            return bool(success)
        except Exception as e:
            print(f"[Camera] trigger_autofocus error: {e}")
            return False

    def stop(self):
        if self.backend == "picamera2":
            self._handle.stop()
            self._handle.close()
        elif self.backend == "opencv":
            self._handle.release()
        self.backend = None
        self._handle = None
