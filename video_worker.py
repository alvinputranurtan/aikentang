# video_worker.py
import time
import os
import cv2
from PyQt5 import QtCore, QtGui
from ultralytics import YOLO

from config import AppConfig
from db_client import get_threshold, set_current
from telegram_sender import TelegramSender


def load_model_for_age(cfg: AppConfig, umur_hari: int) -> YOLO:
    if umur_hari <= cfg.MODEL_AGE_SWITCH_DAYS:
        path = cfg.PATH_MODEL_1 if os.path.exists(cfg.PATH_MODEL_1) else "yolov8n.pt"
    else:
        path = cfg.PATH_MODEL_2 if os.path.exists(cfg.PATH_MODEL_2) else "yolov8s.pt"
    return YOLO(path)


def build_csi_gstreamer_pipeline(width=1920, height=1080, fps=30, flip_method=0) -> str:
    """
    Pipeline CSI Jetson -> OpenCV (CPU BGR).
    NOTE: format NV12 + memory:NVMM is important for Argus.
    """
    return (
        "nvarguscamerasrc ! "
        f"video/x-raw(memory:NVMM), width={width}, height={height}, framerate={fps}/1, format=NV12 ! "
        f"nvvidconv flip-method={flip_method} ! "
        "video/x-raw, format=BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


class VideoWorker(QtCore.QThread):
    frame_updated = QtCore.pyqtSignal(QtGui.QImage)
    log_signal = QtCore.pyqtSignal(str)

    # UI status: "stopped" | "normal" | "malnutrisi" | "no_plant"
    status_signal = QtCore.pyqtSignal(str)

    def __init__(self, cfg: AppConfig, model: YOLO, tg: TelegramSender):
        super().__init__()
        self.cfg = cfg
        self.model = model
        self.tg = tg

        self.running = False

        self.threshold = {"n": 0, "p": 0, "k": 0}
        self.dead_hits = 0
        self.dead_state = False
        self.last_dead_seen_ts = 0.0
        self.last_db_update_ts = 0.0

        self.last_annotated_bgr = None

        # Camera settings (override via cfg if you want)
        self.cam_width = getattr(cfg, "CAM_WIDTH", 1920)
        self.cam_height = getattr(cfg, "CAM_HEIGHT", 1080)
        self.cam_fps = getattr(cfg, "CAM_FPS", 30)
        self.csi_flip_method = getattr(cfg, "CSI_FLIP_METHOD", 0)

        # Keep your old behavior (mirror)
        self.mirror = getattr(cfg, "CAM_MIRROR", True)

        # Fallback behavior
        self.use_usb_fallback = getattr(cfg, "USE_USB_FALLBACK", False)
        self.usb_index = getattr(cfg, "USB_CAM_INDEX", 0)

        # Robustness
        self.max_consecutive_read_fail = getattr(cfg, "CAM_MAX_READ_FAIL", 60)  # ~2s if sleep 0.03
        self.read_fail_count = 0

        # track last UI status to avoid spamming
        self._last_status_sent = None

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    def _emit_status(self, status: str):
        if status != self._last_status_sent:
            self.status_signal.emit(status)
            self._last_status_sent = status

    def _open_csi(self):
        pipeline = build_csi_gstreamer_pipeline(
            width=self.cam_width,
            height=self.cam_height,
            fps=self.cam_fps,
            flip_method=self.csi_flip_method,
        )
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        return cap if cap.isOpened() else None

    def _open_usb(self):
        cap = cv2.VideoCapture(int(self.usb_index), cv2.CAP_V4L2)
        return cap if cap.isOpened() else None

    def _open_camera(self):
        cap = self._open_csi()
        if cap is not None:
            self._log(
                f"[CAM] CSI opened: {self.cam_width}x{self.cam_height}@{self.cam_fps} "
                f"(flip={self.csi_flip_method})"
            )
            return cap, "csi"

        self._log("[CAM] CSI open failed.")
        if self.use_usb_fallback:
            cap = self._open_usb()
            if cap is not None:
                self._log(f"[CAM] USB opened: index={self.usb_index}")
                return cap, "usb"
            self._log("[CAM] USB fallback failed too.")

        return None, "none"

    def _restart_argus(self):
        try:
            import subprocess
            self._log("[CAM] Restarting nvargus-daemon...")
            subprocess.run(["sudo", "systemctl", "restart", "nvargus-daemon"], check=False)
            time.sleep(1.0)
        except Exception as e:
            self._log(f"[CAM] Restart nvargus-daemon failed: {e}")

    def run(self):
        # Load DB thresholds
        try:
            self.threshold = get_threshold(self.cfg, self.cfg.DEVICE_ID)
            self._log(f"[DB] Threshold loaded: {self.threshold}")
        except Exception as e:
            self._log(f"[DB] ERROR load threshold: {e}")

        self._log(f"[MODEL] classes: {self.model.names}")
        self._log(
            f"[CFG] DEAD='{self.cfg.DEAD_CLASS_NAME}', CONF={self.cfg.DEAD_CONF}, HITS={self.cfg.DEAD_HITS_REQUIRED}, "
            f"RECOVER={self.cfg.RECOVER_AFTER_SEC}s, DB_CD={self.cfg.DB_COOLDOWN_SEC}s, "
            f"TG={self.cfg.telegram_enabled()} (CD={self.cfg.TG_COOLDOWN_SEC}s)"
        )

        cap, cam_type = self._open_camera()
        if cap is None:
            self._log("[CAM] ERROR: cannot open camera.")
            self._emit_status("no_plant")
            return

        self.running = True
        self._emit_status("normal")
        self.read_fail_count = 0

        while self.running:
            ret, frame = cap.read()

            if (not ret) or (frame is None):
                self.read_fail_count += 1
                if self.read_fail_count % 30 == 0:
                    self._log(f"[CAM] read() failed x{self.read_fail_count}")

                if self.read_fail_count >= self.max_consecutive_read_fail:
                    self._log("[CAM] Too many read failures -> reopening camera.")
                    cap.release()

                    if cam_type == "csi":
                        self._restart_argus()

                    cap, cam_type = self._open_camera()
                    if cap is None:
                        self._log("[CAM] Reopen failed. Stopping worker.")
                        break
                    self.read_fail_count = 0

                time.sleep(0.03)
                continue

            self.read_fail_count = 0

            if self.mirror:
                frame = cv2.flip(frame, 1)

            # YOLO inference
            results = self.model.predict(frame, verbose=False)
            r0 = results[0]
            annotated = r0.plot()
            self.last_annotated_bgr = annotated

            # ---- detect "no plant" ----
            has_boxes = (r0.boxes is not None) and (len(r0.boxes) > 0)
            if not has_boxes:
                self._emit_status("no_plant")
                self.dead_hits = max(0, self.dead_hits - 1)

                rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                img_qt = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
                self.frame_updated.emit(img_qt)

                time.sleep(0.01)
                continue

            # ---- detect dead (UI label: MALNUTRISI) ----
            dead_detected = False
            best_dead_conf = 0.0

            cls_ids = r0.boxes.cls.cpu().numpy().astype(int)
            confs = r0.boxes.conf.cpu().numpy()
            for cid, cf in zip(cls_ids, confs):
                name = self.model.names.get(int(cid), str(cid))
                cf = float(cf)
                if name == self.cfg.DEAD_CLASS_NAME and cf >= self.cfg.DEAD_CONF:
                    dead_detected = True
                    best_dead_conf = max(best_dead_conf, cf)

            now = time.time()
            if dead_detected:
                self.last_dead_seen_ts = now

            # debounce hits
            if dead_detected:
                self.dead_hits += 1
            else:
                self.dead_hits = max(0, self.dead_hits - 1)

            # NORMAL -> MALNUTRISI trigger
            if (not self.dead_state) and (self.dead_hits >= self.cfg.DEAD_HITS_REQUIRED):
                self.dead_state = True
                self._emit_status("malnutrisi")

                if (now - self.last_db_update_ts) >= self.cfg.DB_COOLDOWN_SEC:
                    try:
                        affected = set_current(self.cfg, self.cfg.DEVICE_ID, 0, 0, 0)
                        self._log(f"[DB] MALNUTRISI(trigger by DEAD) -> set current=0 (affected={affected})")
                        self.last_db_update_ts = now
                    except Exception as e:
                        self._log(f"[DB] ERROR set current=0: {e}")

                if self.cfg.telegram_enabled() and self.last_annotated_bgr is not None:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    caption = (
                        f"⚠️ DETEKSI MALNUTRISI\n"
                        f"Waktu: {ts}\n"
                        f"Device ID: {self.cfg.DEVICE_ID}\n"
                        f"hits: {self.dead_hits}\n"
                        f"conf_best: {best_dead_conf:.2f}\n"
                        f"Action: set current=0"
                    )
                    ok, buf = cv2.imencode(".jpg", self.last_annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    if ok:
                        queued = self.tg.enqueue_photo(buf.tobytes(), caption)
                        self._log("[TG] queued snapshot" if queued else "[TG] queue full, skip")

            # if not malnutrisi state, and plants exist, set normal
            if not self.dead_state and has_boxes:
                self._emit_status("normal")

            # MALNUTRISI -> RECOVER trigger
            if self.dead_state:
                no_dead_sec = now - self.last_dead_seen_ts
                if no_dead_sec >= self.cfg.RECOVER_AFTER_SEC:
                    n = int(self.threshold.get("n", 0)) + 1
                    p = int(self.threshold.get("p", 0)) + 1
                    k = int(self.threshold.get("k", 0)) + 1

                    if (now - self.last_db_update_ts) >= self.cfg.DB_COOLDOWN_SEC:
                        try:
                            affected = set_current(self.cfg, self.cfg.DEVICE_ID, n, p, k)
                            self._log(f"[DB] RECOVER -> set current=threshold+1 ({n},{p},{k}) (affected={affected})")
                            self.last_db_update_ts = now
                        except Exception as e:
                            self._log(f"[DB] ERROR set current=threshold+1: {e}")

                    self.dead_state = False
                    self.dead_hits = 0
                    self._emit_status("normal")

            # send frame to UI
            rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            img_qt = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
            self.frame_updated.emit(img_qt)

        try:
            cap.release()
        except Exception:
            pass
        self._log(f"[CAM] Released ({cam_type}).")

        # when thread ends, tell UI stopped
        self._emit_status("stopped")

    def stop(self):
        self.running = False
        self.quit()
        self.wait()
