"""Pi4 brain dieu phoi BLE, Firebase, pipeline AI va upload anh ket qua.
File nay la entrypoint chay tren Raspberry Pi trong he thong that.
"""
import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

try:
    import requests
except ImportError:
    requests = None

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.characteristic import BleakGATTCharacteristic
except ImportError:
    print("[ERROR] Thiếu bleak. Chạy: pip install bleak")
    sys.exit(1)


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)


def _repo_path_from_env(name: str, default_relative: str) -> str:
    raw = os.getenv(name, "")
    if raw:
        path = Path(raw)
        return str(path if path.is_absolute() else BASE_DIR / path)
    return str(BASE_DIR / default_relative)


# Tat ca khoa va mat khau doc tu bien moi truong de tranh lo thong tin khi nop code.
FIREBASE_API_KEY    = os.getenv("FIREBASE_API_KEY", "")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_RTDB_URL    = os.getenv("FIREBASE_RTDB_URL", "")

DEVICE_EMAIL    = os.getenv("DEVICE_EMAIL", "")
DEVICE_PASSWORD = os.getenv("DEVICE_PASSWORD", "")
DEVICE_UID      = os.getenv("DEVICE_UID", "")

# Duong dan du lieu tren Firestore va Realtime Database.
DOC_SYSTEM_CONFIG = "system_config/current"
DOC_SYSTEM_STATUS = "system_status/current"
RTDB_CONTROL_PATH = "control"
RTDB_LIVE_PATH    = "live"
RTDB_DEVICE_PATH  = "device"

DEVICE_ID  = "pi4-brain-01"
FW_VERSION = "3.0.0"

# Ten va UUID BLE cua ESP32 dieu khien ray truot.
RAIL_NAME = "TomatoRail-ESP32"
SVC_UUID  = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
CMD_UUID  = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
STA_UUID  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


# Cac chu ky thoi gian dieu khien. Gia tri nho giup app phan hoi nhanh hon.
CONTROL_POLL_S         = 0.8
LIVE_PUSH_S            = 1.5
DEVICE_PUSH_S          = 10.0
IDLE_CONFIG_POLL_S     = 60.0
BOUNDARY_CONFIG_POLL_S = 2.0
CONFIG_ACK_TIMEOUT_S   = 5.0
BLE_WRITE_CHUNK_BYTES  = 180
BLE_MAX_CMD_LINE_BYTES = 512
PHOTO_HOLD_S           = 2.0
READY_WAIT_S           = 1.8
BLE_SCAN_TIMEOUT_S     = 8.0
BLE_RECONNECT_DELAY_S  = 3.0
AI_TIMEOUT_S            = 45.0


# Duong dan pipeline AI duoc goi moi khi xe dung o vi tri chup.
PIPELINE_SCRIPT = _repo_path_from_env("PIPELINE_SCRIPT", "scripts/pipeline.py")
AI_RESULT_DIR   = _repo_path_from_env("AI_RESULT_DIR", "ai_results")


# Cloudinary chi upload anh khi co ket qua benh de tiet kiem dung luong.
CLOUDINARY_CLOUD_NAME    = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY       = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET    = os.getenv("CLOUDINARY_API_SECRET", "")
CLOUDINARY_UPLOAD_PRESET = os.getenv("CLOUDINARY_UPLOAD_PRESET", "")
CLOUDINARY_FOLDER        = os.getenv("CLOUDINARY_FOLDER", "aiot_tomato")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pi4_brain")


def _utc_timestamp_value() -> str:

    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _fs_encode(value: Any) -> dict:
    # Firestore REST API yeu cau moi gia tri phai co kieu du lieu ro rang.
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        if value.endswith("Z") and "T" in value:
            return {"timestampValue": value}
        return {"stringValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {str(k): _fs_encode(v) for k, v in value.items()}}}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_fs_encode(v) for v in value]}}
    return {"stringValue": str(value)}
def _fs_encode_doc(data: dict) -> dict:
    return {"fields": {str(k): _fs_encode(v) for k, v in data.items()}}

def _fs_decode_value(v: dict) -> Any:
    if not isinstance(v, dict):
        return None
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return bool(v.get("booleanValue"))
    if "integerValue" in v:
        try:
            return int(v.get("integerValue", 0))
        except Exception:
            return 0
    if "doubleValue" in v:
        try:
            return float(v.get("doubleValue", 0.0))
        except Exception:
            return 0.0
    if "stringValue" in v:
        return v.get("stringValue", "")
    if "timestampValue" in v:
        return v.get("timestampValue", "")
    if "arrayValue" in v:
        return [_fs_decode_value(x) for x in v.get("arrayValue", {}).get("values", [])]
    if "mapValue" in v:
        return {k: _fs_decode_value(val) for k, val in v.get("mapValue", {}).get("fields", {}).items()}
    return None

def _fs_decode_doc(doc: dict) -> dict:
    return {k: _fs_decode_value(v) for k, v in doc.get("fields", {}).items()}

# Lop nay boc cac thao tac Auth, Firestore va Realtime Database bang REST API.
class FirebaseClient:

    def __init__(self):
        if requests is None:
            log.error("[Firebase] Thiếu requests. Chạy: pip install requests")
            sys.exit(1)
        missing = []
        for name, value in {
            "FIREBASE_API_KEY": FIREBASE_API_KEY,
            "FIREBASE_PROJECT_ID": FIREBASE_PROJECT_ID,
            "FIREBASE_RTDB_URL": FIREBASE_RTDB_URL,
            "DEVICE_EMAIL": DEVICE_EMAIL,
            "DEVICE_PASSWORD": DEVICE_PASSWORD,
            "DEVICE_UID": DEVICE_UID,
        }.items():
            if not value:
                missing.append(name)
        if missing:
            log.error("[Firebase] Thiếu biến môi trường: " + ", ".join(missing))
            sys.exit(1)

        self.api_key = FIREBASE_API_KEY
        self.project_id = FIREBASE_PROJECT_ID
        self.rtdb_url = FIREBASE_RTDB_URL.rstrip("/")
        self.email = DEVICE_EMAIL
        self.password = DEVICE_PASSWORD
        self.expected_uid = DEVICE_UID

        self.id_token = ""
        self.refresh_token = ""
        self.uid = ""
        self.expires_at = 0.0

        self.fs_base = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents"

    def sign_in(self):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        payload = {
            "email": self.email,
            "password": self.password,
            "returnSecureToken": True,
        }
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code >= 400:
            log.error(f"[Firebase Auth] signIn fail {resp.status_code}: {resp.text[:500]}")
            sys.exit(1)
        data = resp.json()
        self.id_token = data["idToken"]
        self.refresh_token = data["refreshToken"]
        self.uid = data.get("localId", "")
        self.expires_at = time.time() + int(data.get("expiresIn", "3600")) - 300

        if self.uid != self.expected_uid:
            log.error(f"[Firebase Auth] UID sai. Auth UID={self.uid}, expected={self.expected_uid}")
            sys.exit(1)
        log.info(f"[Firebase Auth] signed in as device uid={self.uid}")

    def refresh_if_needed(self):
        if self.id_token and time.time() < self.expires_at:
            return
        if not self.refresh_token:
            self.sign_in()
            return
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"
        payload = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        resp = requests.post(url, data=payload, timeout=20)
        if resp.status_code >= 400:
            log.warning(f"[Firebase Auth] refresh fail {resp.status_code}, sign in lại")
            self.sign_in()
            return
        data = resp.json()
        self.id_token = data["id_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self.uid = data.get("user_id", self.uid)
        self.expires_at = time.time() + int(data.get("expires_in", "3600")) - 300
        log.info("[Firebase Auth] token refreshed")

    def _auth_headers(self) -> dict:
        self.refresh_if_needed()
        return {"Authorization": f"Bearer {self.id_token}"}

    def _rtdb_url(self, path: str) -> str:
        self.refresh_if_needed()
        path = path.strip("/")
        return f"{self.rtdb_url}/{path}.json?auth={self.id_token}"


    def rtdb_get(self, path: str) -> Optional[dict]:
        try:
            resp = requests.get(self._rtdb_url(path), timeout=15)
            if resp.status_code >= 400:
                log.error(f"[RTDB] GET {path} fail {resp.status_code}: {resp.text[:300]}")
                return None
            return resp.json()
        except Exception as e:
            log.error(f"[RTDB] GET {path}: {e}")
            return None

    def rtdb_put(self, path: str, data: dict) -> bool:
        try:
            resp = requests.put(self._rtdb_url(path), json=data, timeout=15)
            if resp.status_code >= 400:
                log.error(f"[RTDB] PUT {path} fail {resp.status_code}: {resp.text[:300]}")
                return False
            return True
        except Exception as e:
            log.error(f"[RTDB] PUT {path}: {e}")
            return False

    def rtdb_patch(self, path: str, data: dict) -> bool:
        try:
            resp = requests.patch(self._rtdb_url(path), json=data, timeout=15)
            if resp.status_code >= 400:
                log.error(f"[RTDB] PATCH {path} fail {resp.status_code}: {resp.text[:300]}")
                return False
            return True
        except Exception as e:
            log.error(f"[RTDB] PATCH {path}: {e}")
            return False


    def fs_get_doc(self, doc_path: str) -> Optional[dict]:
        try:
            url = f"{self.fs_base}/{doc_path.strip('/')}"
            resp = requests.get(url, headers=self._auth_headers(), timeout=20)
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                log.error(f"[FS] GET {doc_path} fail {resp.status_code}: {resp.text[:500]}")
                return None
            return _fs_decode_doc(resp.json())
        except Exception as e:
            log.error(f"[FS] GET {doc_path}: {e}")
            return None

    def fs_patch_doc(self, doc_path: str, data: dict) -> bool:
        try:
            url = f"{self.fs_base}/{doc_path.strip('/')}"
            params = [("updateMask.fieldPaths", k) for k in data.keys()]
            resp = requests.patch(
                url,
                headers=self._auth_headers(),
                params=params,
                json=_fs_encode_doc(data),
                timeout=20,
            )
            if resp.status_code >= 400:
                log.error(f"[FS] PATCH {doc_path} fail {resp.status_code}: {resp.text[:500]}")
                return False
            return True
        except Exception as e:
            log.error(f"[FS] PATCH {doc_path}: {e}")
            return False

    def fs_add_doc(self, collection_path: str, data: dict) -> Optional[str]:
        try:
            url = f"{self.fs_base}/{collection_path.strip('/')}"
            resp = requests.post(
                url,
                headers=self._auth_headers(),
                json=_fs_encode_doc(data),
                timeout=20,
            )
            if resp.status_code >= 400:
                log.error(f"[FS] ADD {collection_path} fail {resp.status_code}: {resp.text[:500]}")
                return None
            name = resp.json().get("name", "")
            return name.rsplit("/", 1)[-1] if name else None
        except Exception as e:
            log.error(f"[FS] ADD {collection_path}: {e}")
            return None

_fb: Optional[FirebaseClient] = None

def init_firebase():
    global _fb
    _fb = FirebaseClient()
    _fb.sign_in()
    log.info("[Firebase] REST client OK - Security Rules đang có hiệu lực")

def _firebase() -> FirebaseClient:
    if _fb is None:
        raise RuntimeError("Firebase chưa init")
    return _fb


def fs_get_config() -> Optional[dict]:
    return _firebase().fs_get_doc(DOC_SYSTEM_CONFIG)

def fs_patch_status(data: dict):
    return _firebase().fs_patch_doc(DOC_SYSTEM_STATUS, data)

def fs_add_scan_result(data: dict) -> Optional[str]:
    return _firebase().fs_add_doc("scan_results", data)


def rtdb_get(path: str) -> Optional[dict]:
    return _firebase().rtdb_get(path)

def rtdb_put(path: str, data: dict):
    return _firebase().rtdb_put(path, data)

def rtdb_patch(path: str, data: dict):
    return _firebase().rtdb_patch(path, data)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _clean_firestore_payload(obj: Any) -> Any:

    if isinstance(obj, dict):
        return {str(k): _clean_firestore_payload(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_firestore_payload(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)

# Chuan hoa nhan de app va Firestore khong bi lech ten label.
def normalize_label(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    raw = raw.replace("__", "_")
    if raw in ("leafminer", "leaf_miner", "leaf_miner_", "leaf_miner."):
        return "leafminer"
    if raw in ("earlyblight", "early_blight", "early_blight_"):
        return "earlyblight"
    if raw in ("diseased", "diseased(?)", "diseased_?", "diseased_unknown", "disease"):
        return "diseased_unknown"
    if raw in ("healthy", "health"):
        return "healthy"
    if raw in ("uncertain", "unknown", "none", "no_leaf", "no_detection", ""):
        return raw or "unknown"
    return raw

def should_upload_result(result: dict, label: str) -> bool:
    # Chi upload va luu scan result khi co benh ro rang.
    if label in ("healthy", "uncertain", "unknown", "no_leaf", "no_detection", ""):
        return False
    explicit = result.get("has_disease")
    if explicit is False:
        return False
    if explicit is True:
        return True
    return label in ("leafminer", "earlyblight", "diseased_unknown")

def scan_status_from_label(label: str, uploadable: bool, result: dict) -> str:
    if str(result.get("scan_status", "")).strip():
        return str(result.get("scan_status")).strip().lower()
    if uploadable:
        return "diseased"
    if label == "healthy":
        return "healthy"
    if label == "uncertain":
        return "uncertain"
    if label in ("unknown", "no_leaf", "no_detection", ""):
        return "uncertain"
    return "uncertain"

def cloudinary_ready() -> bool:
    if not CLOUDINARY_CLOUD_NAME:
        return False

    return bool(CLOUDINARY_CLOUD_NAME and (CLOUDINARY_UPLOAD_PRESET or (CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)))

def upload_image_to_cloudinary(image_path: str, public_id: str) -> dict:
    # Upload anh annotated len Cloudinary roi tra ve secure url cho ung dung.
    if not cloudinary_ready():
        log.warning("[Cloudinary] Chưa cấu hình CLOUDINARY_*. Bỏ qua upload ảnh.")
        return {}
    if requests is None:
        log.error("[Cloudinary] Thiếu requests. Chạy: pip install requests")
        return {}

    path = Path(image_path)
    if not path.exists():
        log.error(f"[Cloudinary] Không tìm thấy ảnh: {path}")
        return {}

    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"
    data = {
        "folder": CLOUDINARY_FOLDER,
        "public_id": public_id,
    }

    if CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        timestamp = str(int(time.time()))
        data["timestamp"] = timestamp
        sign_payload = "&".join(f"{k}={v}" for k, v in sorted(data.items()) if v not in (None, ""))
        signature = hashlib.sha1((sign_payload + CLOUDINARY_API_SECRET).encode("utf-8")).hexdigest()
        data["api_key"] = CLOUDINARY_API_KEY
        data["signature"] = signature
    else:
        data["upload_preset"] = CLOUDINARY_UPLOAD_PRESET

    with path.open("rb") as f:
        resp = requests.post(url, data=data, files={"file": f}, timeout=30)
    if resp.status_code >= 400:
        log.error(f"[Cloudinary] upload fail {resp.status_code}: {resp.text[:300]}")
        return {}

    out = resp.json()
    log.info(f"[Cloudinary] uploaded {out.get('public_id', public_id)}")
    return {
        "secure_url": out.get("secure_url", ""),
        "public_id": out.get("public_id", public_id),
        "width": out.get("width"),
        "height": out.get("height"),
        "bytes": out.get("bytes"),
        "format": out.get("format"),
    }


def _safe_int(value, default=0, min_value=None, max_value=None):
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default
    if min_value is not None:
        out = max(min_value, out)
    if max_value is not None:
        out = min(max_value, out)
    return out

def parse_config(raw: dict) -> Optional[dict]:
    # Doc cau hinh vi tri quet tu Firestore va gioi han trong hanh trinh ray.
    if not raw:
        return None

    positions = []
    for p in raw.get("positions", []):
        try:
            cm = float(p)
        except (TypeError, ValueError):
            continue
        if 0 <= cm <= 81:
            positions.append(cm)

    if not positions:
        return None

    positions = sorted(set(positions))
    # Truong mode duoc giu de tuong thich cau hinh cu; ban hien tai chi quet mot chieu.
    mode = "S"
    policy = "manual_restart" if str(raw.get("apply_policy", "")).strip().lower() == "manual_restart" else "after_route"
    return {
        "version":          _safe_int(raw.get("version"), 0, 0),
        "num_scans":        _safe_int(raw.get("num_scans"), 1, 1),
        "interval_minutes": _safe_int(raw.get("interval_minutes"), 0, 0),
        "start_hour":       _safe_int(raw.get("start_hour"), 0, 0, 23),
        "start_minute":     _safe_int(raw.get("start_minute"), 0, 0, 59),
        "mode":             mode,
        "apply_policy":     policy,
        "positions":        positions,
    }

# Lenh CFG gui sang ESP32 gom mode va danh sach vi tri cm.
def build_config_cmd(cfg: dict) -> str:
    pos_str = ",".join(f"{p:.1f}".rstrip("0").rstrip(".") for p in cfg["positions"])
    return f"C:V{cfg['version']},{cfg['num_scans']},{cfg['interval_minutes']},{cfg['mode']},{pos_str}"

def positions_equal(a: dict, b: dict) -> bool:
    pa, pb = a["positions"], b["positions"]
    if len(pa) != len(pb):
        return False
    return all(abs(x - y) < 0.05 for x, y in zip(pa, pb))


# RailBrain giu trang thai he thong va dieu phoi lenh app, ESP32, AI pipeline.
class RailBrain:
    def __init__(self):

        self._client: Optional[BleakClient] = None
        self._ble_connected = False
        self._config_ack    = asyncio.Event()


        self._cfg: Optional[dict] = None
        self._loaded_version = -1
        self._current_run_id = ""


        self._run_active     = False
        self._is_paused      = False
        self._rail_state     = "idle"
        self._apply_status   = "synced"


        self._current_cm  = 0.0
        self._target_cm   = 0.0
        self._arrived_cm  = 0.0


        self._pending_arrived = ""
        self._active_arrived  = ""
        self._handled_arrived = ""
        self._arrival_pending   = False
        self._photo_wait_active = False
        self._photo_wait_start  = 0.0


        self._need_reconcile = False
        self._status_dirty    = True
        self._last_status_push = 0.0
        self._last_live_push   = 0.0
        self._last_device_push = 0.0
        self._last_ctrl_poll   = 0.0
        self._last_idle_cfg    = 0.0
        self._last_boundary    = 0.0
        self._last_handled_req = 0


    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray):
        msg = data.decode(errors="replace").strip()
        if not msg:
            return
        log.info(f"[ESP32->] {msg}")

        if msg == "READY":
            if not self._run_active and not self._is_paused:
                self._set_state("idle")

        elif msg == "CONFIG_OK":
            self._config_ack.set()

        elif msg.startswith("MOVING:"):
            self._is_paused  = False
            self._run_active = True
            self._target_cm  = float(msg[7:])
            self._set_state("moving")

        elif msg.startswith("ARRIVED:"):
            self._is_paused  = False
            self._run_active = True
            v = float(msg[8:])
            self._arrived_cm = v
            self._current_cm = v
            self._target_cm  = v
            self._set_state("waiting_next")
            if msg not in (self._handled_arrived, self._active_arrived, self._pending_arrived):
                self._pending_arrived = msg
                self._arrival_pending = True

        elif msg == "INTERVAL_WAIT":
            self._is_paused  = False
            self._run_active = True
            self._set_state("interval_wait")

        elif msg == "PAUSED":
            self._run_active = False
            self._is_paused  = True
            self._clear_photo_state()
            self._set_state("paused")

        elif msg == "STOPPED":
            self._run_active = False
            self._is_paused  = False
            self._clear_photo_state()
            self._set_state("stopped")

        elif msg == "COMPLETE":
            self._run_active     = False
            self._is_paused      = False
            self._target_cm      = self._current_cm
            self._need_reconcile = True
            self._clear_photo_state()
            self._set_state("completed")

        elif msg == "ESTOP" or msg.startswith("ESTOP:") or msg.startswith("ERROR"):
            self._run_active = False
            self._is_paused  = False
            self._clear_photo_state()
            self._set_state("stopped" if "LIMIT" in msg or msg == "ESTOP" else "error")
            if "error" in self._rail_state:
                self._apply_status = "error"

    def _clear_photo_state(self):
        self._photo_wait_active = False
        self._arrival_pending   = False
        self._pending_arrived   = ""
        self._active_arrived    = ""
        self._handled_arrived   = ""

    def _set_state(self, state: str):
        if self._rail_state != state:
            self._rail_state  = state
            self._status_dirty = True
            log.info(f"[STATE] {state}")


    async def _send(self, cmd: str) -> bool:
        if not self._client or not self._ble_connected:
            log.warning(f"[BLE] cannot send {cmd}: disconnected")
            return False
        try:
            out = (cmd + "\n").encode()
            await self._client.write_gatt_char(CMD_UUID, out, response=False)
            log.info(f"[->ESP32] {cmd}")
            return True
        except Exception as e:
            log.error(f"[BLE] send fail: {e}")
            self._ble_connected = False
            self._status_dirty = True
            return False

    async def _send_line_chunked(self, cmd: str) -> bool:
        if not self._client or not self._ble_connected:
            log.warning("[BLE] cannot send config: disconnected")
            return False
        payload = cmd.encode("utf-8")
        if len(payload) > BLE_MAX_CMD_LINE_BYTES:
            log.warning(
                f"[CFG] command too long: {len(payload)} > {BLE_MAX_CMD_LINE_BYTES} bytes"
            )
            return False
        try:
            framed = payload + b"\n"
            for offset in range(0, len(framed), BLE_WRITE_CHUNK_BYTES):
                await self._client.write_gatt_char(
                    CMD_UUID,
                    framed[offset:offset + BLE_WRITE_CHUNK_BYTES],
                    response=False,
                )
            log.info(f"[->ESP32] config ({len(payload)} bytes)")
            return True
        except Exception as e:
            log.error(f"[BLE] config send fail: {e}")
            self._ble_connected = False
            self._status_dirty = True
            return False

    async def _send_config(self) -> bool:
        if not self._cfg:
            return False
        cmd = build_config_cmd(self._cfg)
        self._config_ack.clear()
        if not await self._send_line_chunked(cmd):
            return False
        try:
            await asyncio.wait_for(self._config_ack.wait(), timeout=CONFIG_ACK_TIMEOUT_S)
            return True
        except asyncio.TimeoutError:
            log.warning("[CFG] CONFIG_OK timeout")
            return False


    async def _scan_and_connect(self) -> bool:
        log.info("[BLE] scanning...")
        device = await BleakScanner.find_device_by_name(RAIL_NAME, timeout=BLE_SCAN_TIMEOUT_S)
        if not device:
            log.warning(f"[BLE] '{RAIL_NAME}' không tìm thấy")
            return False

        log.info(f"[BLE] found {device.address} - connecting...")
        self._client = BleakClient(
            device,
            disconnected_callback=self._on_disconnected,
        )
        try:
            await self._client.connect()
            await self._client.start_notify(STA_UUID, self._on_notify)
            self._ble_connected = True
            log.info("[BLE] connected")
            return True
        except Exception as e:
            log.error(f"[BLE] connect fail: {e}")
            self._ble_connected = False
            return False

    def _on_disconnected(self, _):
        log.warning("[BLE] disconnected")
        self._ble_connected = False
        self._run_active     = False
        # Chi callback PAUSED moi cho phep mot yeu cau RUN chuyen thanh RESUME.
        self._is_paused      = False
        self._status_dirty   = True


    def _load_cfg(self, cfg: dict):
        self._cfg            = cfg
        self._loaded_version = cfg["version"]
        self._apply_status   = "synced"
        self._status_dirty   = True
        log.info(f"[CFG] loaded v{self._loaded_version}")

    async def _fetch_cfg(self) -> Optional[dict]:
        raw = fs_get_config()
        return parse_config(raw) if raw else None

    async def _idle_refresh(self):
        cfg = await self._fetch_cfg()
        if not cfg:
            return
        if not self._cfg or cfg["version"] != self._loaded_version:
            log.info("[CFG] idle refresh")
            self._apply_status = "updating"
            self._push_status()
            self._load_cfg(cfg)

    async def _reconcile_after_route(self):
        cfg = await self._fetch_cfg()
        if not cfg:
            self._apply_status = "error"
            self._status_dirty = True
            return
        if not self._cfg or cfg["version"] == self._loaded_version:
            self._apply_status = "synced"
            self._status_dirty = True
            return
        if cfg["apply_policy"] == "after_route":
            if not positions_equal(cfg, self._cfg):
                self._apply_status = "waiting_manual_restart"
            else:
                self._apply_status = "updating"
                self._push_status()
                self._load_cfg(cfg)
                self._apply_status = "synced"
        else:
            self._apply_status = "waiting_manual_restart"
        self._status_dirty = True

    async def _reconcile_at_boundary(self):
        if not self._run_active or self._is_paused or self._rail_state != "interval_wait":
            return
        cfg = await self._fetch_cfg()
        if not cfg or cfg["version"] == self._loaded_version:
            return
        if cfg["apply_policy"] != "after_route":
            self._apply_status = "waiting_manual_restart"
            self._status_dirty = True
            return
        if not positions_equal(cfg, self._cfg):
            self._apply_status = "waiting_manual_restart"
            self._status_dirty = True
            return
        log.info("[CFG] apply at boundary")
        self._apply_status = "updating"
        self._push_status()
        self._load_cfg(cfg)
        if not await self._send_config():
            self._apply_status = "error"
        self._status_dirty = True


    async def _start_run(self) -> bool:
        if not self._cfg or not self._ble_connected:
            return False
        self._current_run_id = time.strftime("run_%Y%m%d_%H%M%S")
        self._clear_photo_state()
        self._target_cm    = 0.0
        self._apply_status = "synced"
        self._push_status()

        await asyncio.sleep(READY_WAIT_S)

        if not await self._send_config():
            self._run_active = False
            self._set_state("error")
            return False
        if not await self._send("START"):
            self._set_state("error")
            return False
        log.info("[RUN] started")
        return True

    async def _prepare_and_start(self) -> bool:
        cfg = await self._fetch_cfg()
        if not cfg:
            self._apply_status = "error"
            self._status_dirty = True
            return False
        if not self._cfg or cfg["version"] != self._loaded_version:
            self._apply_status = "updating"
            self._push_status()
            self._load_cfg(cfg)
        self._apply_status = "synced"
        self._status_dirty = True
        return await self._start_run()

    async def _pause_from_ctrl(self):
        log.info("[CTRL] PAUSE")
        if not await self._send("PAUSE"):
            log.warning("[CTRL] PAUSE not applied because BLE send failed")

    async def _stop_from_ctrl(self):
        log.info("[CTRL] STOP")
        if not await self._send("STOP"):
            log.warning("[CTRL] STOP not applied because BLE send failed")

    async def _run_from_ctrl(self):
        if self._run_active or self._photo_wait_active:
            log.info("[CTRL] RUN ignored (busy)")
            return
        cfg = await self._fetch_cfg()
        if not cfg:
            log.warning("[CTRL] RUN: no config")
            return
        same = self._cfg and cfg["version"] == self._loaded_version
        if self._is_paused and same:
            log.info("[CTRL] RUN => RESUME")
            if await self._send("RESUME"):
                log.info("[CTRL] RESUME sent; waiting for ESP32 state")
            else:
                log.warning("[CTRL] RESUME not applied because BLE send failed")
        else:
            log.info("[CTRL] RUN => RESTART")
            await self._prepare_and_start()


    async def _handle_ctrl(self):
        now = time.time()
        if now - self._last_ctrl_poll < CONTROL_POLL_S:
            return
        self._last_ctrl_poll = now

        data = rtdb_get(RTDB_CONTROL_PATH)
        if not data or not isinstance(data, dict):
            return
        req_id = int(data.get("request_id", 0))
        if req_id <= self._last_handled_req:
            return

        log.info(f"[CTRL] req_id={req_id}")
        stop  = data.get("stop_requested",        False)
        pause = data.get("pause_requested",        False)
        nxt   = data.get("manual_next_requested",  False)
        run   = data.get("run_requested",          False)

        if stop:
            await self._stop_from_ctrl()
        elif pause:
            await self._pause_from_ctrl()
        elif nxt:
            # Truong legacy duoc xoa sau khi doc; NEXT van do pipeline AI tu gui.
            log.warning("[CTRL] manual NEXT ignored")
        elif run:
            await self._run_from_ctrl()

        self._last_handled_req = req_id
        rtdb_patch(RTDB_CONTROL_PATH, {
            "stop_requested":        False,
            "pause_requested":       False,
            "manual_next_requested": False,
            "run_requested":         False,
            "request_id":            req_id,
            "updated_at":            int(time.time() * 1000),
            "updated_by":            DEVICE_ID,
        })


    def _run_pipeline_once(self, arrived_cm: float) -> dict:
        # Goi scripts pipeline mot lan tai vi tri xe vua dung va doc JSON tra ve.
        Path(AI_RESULT_DIR).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        json_out = Path(AI_RESULT_DIR) / f"result_{self._current_run_id}_{arrived_cm:.1f}_{ts}.json"

        script = Path(PIPELINE_SCRIPT)
        if not script.exists():
            msg = f"Chưa gắn file phân loại: {PIPELINE_SCRIPT}"
            log.warning(f"[AI] {msg}")
            return {
                "disease": "unknown",
                "confidence": 0.0,
                "has_disease": False,
                "scan_status": "skipped",
                "note": msg,
            }

        cmd = [
            "python3",
            str(script),
            "--single-shot",
            f"--position={arrived_cm:.1f}",
            f"--json-out={json_out}",
        ]
        log.info("[AI] " + " ".join(cmd))
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=AI_TIMEOUT_S,
        )

        if proc.returncode != 0:
            err = proc.stderr[-1000:] or proc.stdout[-1000:]
            log.error(f"[AI] pipeline fail rc={proc.returncode}: {err[-500:]}")
            return {
                "disease": "unknown",
                "confidence": 0.0,
                "has_disease": False,
                "scan_status": "error",
                "note": err,
            }

        if json_out.exists():
            try:
                return json.loads(json_out.read_text(encoding="utf-8"))
            except Exception as e:
                log.error(f"[AI] JSON parse fail {json_out}: {e}")
                return {
                    "disease": "unknown",
                    "confidence": 0.0,
                    "has_disease": False,
                    "scan_status": "error",
                    "note": f"JSON parse fail: {e}",
                }


        try:
            begin = proc.stdout.rfind("{")
            if begin >= 0:
                return json.loads(proc.stdout[begin:])
        except Exception as e:
            log.error(f"[AI] stdout JSON parse fail: {e}")

        log.warning("[AI] Pipeline chạy xong nhưng không trả JSON.")
        return {
            "disease": "unknown",
            "confidence": 0.0,
            "has_disease": False,
            "scan_status": "error",
            "note": "Pipeline không trả JSON.",
            "stdout_tail": proc.stdout[-1000:],
        }

    def _patch_last_scan(self, arrived_cm: float, label: str, confidence: float, status: str, note: str = ""):
        rtdb_patch(RTDB_LIVE_PATH, {
            "last_scan_status": status,
            "last_scan_label": label,
            "last_scan_has_disease": status == "diseased",
            "last_scan_confidence": confidence,
            "last_scan_position_cm": round(arrived_cm, 1),
            "last_scan_at": int(time.time() * 1000),
            "last_scan_note": note[:500] if note else "",
        })

    def _save_ai_result(self, arrived_cm: float, result: dict):
        # Luu ket qua co benh len Firestore va cap nhat live status cho app.
        label_raw = result.get("final_label", result.get("disease", result.get("label", "unknown")))
        label = normalize_label(label_raw)
        confidence = _to_float(result.get("confidence", result.get("conf", 0.0)), 0.0)
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = max(0.0, min(1.0, confidence))

        uploadable = should_upload_result(result, label)
        status = scan_status_from_label(label, uploadable, result)
        note = str(result.get("note") or result.get("error") or "")


        if not uploadable:
            self._patch_last_scan(arrived_cm, label, confidence, status, note)
            log.info(f"[AI] no upload | label={label} conf={confidence:.2f} status={status}")
            return

        image_path = (
            result.get("result_image_path")
            or result.get("annotated_image_path")
            or result.get("image_path")
            or ""
        )
        image_path = str(image_path)
        if not image_path:
            msg = "Có bệnh nhưng pipeline không trả result_image_path. Không lưu scan_results."
            log.error(f"[AI] {msg}")
            self._patch_last_scan(arrived_cm, label, confidence, "error", msg)
            return

        public_id = f"{self._current_run_id}_pos_{arrived_cm:.1f}_{int(time.time())}".replace(".", "_")
        upload = upload_image_to_cloudinary(image_path, public_id)
        if not upload.get("secure_url"):
            msg = "Upload Cloudinary thất bại. Không lưu scan_results để tránh ảnh lỗi trên app."
            log.error(f"[AI] {msg}")
            self._patch_last_scan(arrived_cm, label, confidence, "error", msg)
            return

        doc = {
            "captured_at": _utc_timestamp_value(),
            "position_cm": round(arrived_cm, 1),
            "run_id": self._current_run_id or time.strftime("run_%Y%m%d_%H%M%S"),
            "disease": label,
            "confidence": confidence,
            "has_disease": True,
            "secure_url": upload.get("secure_url", ""),
            "public_id": upload.get("public_id", ""),
            "device_id": DEVICE_ID,
            "loaded_config_version": self._loaded_version,
            "leaf_count": _safe_int(result.get("leaf_count"), 0, 0),
            "summary": _clean_firestore_payload(result.get("summary", {})),
        }
        doc_id = fs_add_scan_result(doc)
        if doc_id:
            log.info(f"[FS] scan_results/{doc_id} saved | {label} {confidence:.2f}")
            self._patch_last_scan(arrived_cm, label, confidence, "diseased", "")

    async def _run_ai(self, arrived_cm: float):
        # Chay AI trong executor de khong chan vong lap BLE va Firebase.
        log.info(f"[AI] capture + classify tại {arrived_cm:.1f} cm")
        loop = asyncio.get_event_loop()
        self._patch_last_scan(arrived_cm, "", 0.0, "running", "")
        try:
            result = await loop.run_in_executor(None, self._run_pipeline_once, arrived_cm)
            await loop.run_in_executor(None, self._save_ai_result, arrived_cm, result)
        except subprocess.TimeoutExpired:
            msg = f"AI timeout sau {AI_TIMEOUT_S}s"
            log.error(f"[AI] {msg}")
            await loop.run_in_executor(None, self._patch_last_scan, arrived_cm, "unknown", 0.0, "error", msg)
        except Exception as e:
            msg = str(e)
            log.exception(f"[AI] unexpected error: {msg}")
            await loop.run_in_executor(None, self._patch_last_scan, arrived_cm, "unknown", 0.0, "error", msg)


    def _push_status(self):
        data = {
            "apply_status":          self._apply_status,
            "rail_state":            self._rail_state,
            "run_active":            self._run_active,
            "loaded_config_version": self._loaded_version,
            "last_arrived_cm":       round(self._arrived_cm, 1),
            "ble_connected":         self._ble_connected,
            "updated_at":            _utc_timestamp_value(),
        }
        fs_patch_status(data)
        self._status_dirty    = False
        self._last_status_push = time.time()

    def _push_live(self):
        rtdb_patch(RTDB_LIVE_PATH, {
            "rail_state":          self._rail_state,
            "run_active":          self._run_active,
            "current_position_cm": round(self._current_cm, 1),
            "target_position_cm":  round(self._target_cm, 1),
            "last_arrived_cm":     round(self._arrived_cm, 1),
            "ble_connected":       self._ble_connected,
            "updated_at":          int(time.time() * 1000),
        })
        self._last_live_push = time.time()

    def _push_device(self):
        rtdb_put(RTDB_DEVICE_PATH, {
            "device_id":  DEVICE_ID,
            "fw_version": FW_VERSION,
            "last_seen":  int(time.time() * 1000),
        })
        self._last_device_push = time.time()


    async def run(self):

        for attempt in range(5):
            cfg = await self._fetch_cfg()
            if cfg:
                self._load_cfg(cfg)
                break
            log.warning(f"[CFG] retry {attempt+1}/5")
            await asyncio.sleep(1.0)
        if not self._cfg:
            log.error("[CFG] không tải được config. Kiểm tra Firebase.")
            sys.exit(1)

        self._push_status()
        self._push_live()
        self._push_device()


        while not self._ble_connected:
            if not await self._scan_and_connect():
                await asyncio.sleep(BLE_RECONNECT_DELAY_S)

        log.info("[BRAIN] entering main loop")

        while True:
            now = time.time()


            if not self._ble_connected:
                log.info("[BLE] reconnecting...")
                self._push_status()
                self._push_live()
                await asyncio.sleep(BLE_RECONNECT_DELAY_S)
                await self._scan_and_connect()
                await asyncio.sleep(0.02)
                continue


            if self._arrival_pending and not self._photo_wait_active:
                self._arrival_pending   = False
                self._active_arrived    = self._pending_arrived
                self._pending_arrived   = ""
                self._photo_wait_active = True
                self._photo_wait_start  = now
                self._set_state("waiting_next")
                log.info(f"[PHOTO] hold {PHOTO_HOLD_S}s | {self._active_arrived}")


            if self._photo_wait_active and now - self._photo_wait_start >= PHOTO_HOLD_S:
                self._photo_wait_active = False
                arrived_cm = self._arrived_cm
                await self._run_ai(arrived_cm)
                if self._run_active and self._ble_connected:
                    self._handled_arrived = self._active_arrived
                    self._active_arrived  = ""
                    log.info("[PHOTO] done -> NEXT")
                    if not await self._send("NEXT"):
                        log.warning("[PHOTO] NEXT send failed; keeping ESP32-reported state")
                else:
                    self._active_arrived = ""


            if self._need_reconcile and not self._run_active:
                self._need_reconcile = False
                await self._reconcile_after_route()
                self._set_state("idle")


            await self._handle_ctrl()


            if (self._run_active and not self._is_paused
                    and self._rail_state == "interval_wait"
                    and now - self._last_boundary >= BOUNDARY_CONFIG_POLL_S):
                self._last_boundary = now
                await self._reconcile_at_boundary()


            if (not self._run_active and not self._photo_wait_active
                    and not self._is_paused
                    and now - self._last_idle_cfg >= IDLE_CONFIG_POLL_S):
                self._last_idle_cfg = now
                await self._idle_refresh()


            if self._status_dirty and now - self._last_status_push >= 0.5:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._push_status)

            if now - self._last_live_push >= LIVE_PUSH_S:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._push_live)

            if now - self._last_device_push >= DEVICE_PUSH_S:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._push_device)

            await asyncio.sleep(0.02)


async def _main():
    log.info("[BOOT] Pi4 BLE Brain starting...")
    init_firebase()
    brain = RailBrain()
    await brain.run()


def main():
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("[BOOT] shutdown")


if __name__ == "__main__":
    main()
