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
    return (
        "nvarguscamerasrc ! "
        f"video/x-raw(memory:NVMM), width={width}, height={height}, framerate={fps}/1, format=NV12 ! "
        f"nvvidconv flip-method={flip_method} ! "
        "video/x-raw, format=BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def _draw_label_box(img, xyxy, label, conf):
    """
    Rules:
      - label == 'malnutrisi'  -> bounding box RED
      - else                  -> bounding box GREEN

    Font made bigger as requested.
    """
    x1, y1, x2, y2 = [int(v) for v in xyxy]

    # colors (BGR)
    if label.lower() == "malnutrisi":
        color = (0, 0, 255)   # red
    else:
        color = (0, 255, 0)   # green

    # thicker box
    box_thickness = 4
    cv2.rectangle(img, (x1, y1), (x2, y2), color, box_thickness)

    # bigger font
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1.2
    text_thickness = 3

    text = f"{label.upper()} {conf:.2f}"
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, text_thickness)

    # label background box
    pad_x, pad_y = 8, 6
    y_text_top = max(0, y1 - th - baseline - (pad_y * 2))
    x_text_left = max(0, x1)

    cv2.rectangle(
        img,
        (x_text_left, y_text_top),
        (x_text_left + tw + (pad_x * 2), y_text_top + th + baseline + (pad_y * 2)),
        color,
        -1,
    )

    # text in black for contrast
    cv2.putText(
        img,
        text,
        (x_text_left + pad_x, y_text_top + th + pad_y),
        font,
        font_scale,
        (0, 0, 0),
        text_thickness,
        cv2.LINE_AA,
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

        # Camera settings
        self.cam_width = getattr(cfg, "CAM_WIDTH", 1920)
        self.cam_height = getattr(cfg, "CAM_HEIGHT", 1080)
        self.cam_fps = getattr(cfg, "CAM_FPS", 30)
        self.csi_flip_method = getattr(cfg, "CSI_FLIP_METHOD", 0)

        self.mirror = getattr(cfg, "CAM_MIRROR", True)

        self.use_usb_fallback = getattr(cfg, "USE_USB_FALLBACK", False)
        self.usb_index = getattr(cfg, "USB_CAM_INDEX", 0)

        self.max_consecutive_read_fail = getattr(cfg, "CAM_MAX_READ_FAIL", 60)
        self.read_fail_count = 0

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

            # Annotated as a copy of frame
            annotated = frame.copy()

            # ---- no plant ----
            has_boxes = (r0.boxes is not None) and (len(r0.boxes) > 0)
            if not has_boxes:
                self._emit_status("no_plant")
                self.dead_hits = max(0, self.dead_hits - 1)

                self.last_annotated_bgr = annotated
                rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                img_qt = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
                self.frame_updated.emit(img_qt)
                time.sleep(0.01)
                continue

            # ---- draw boxes + dead detection ----
            cls_ids = r0.boxes.cls.cpu().numpy().astype(int)
            confs = r0.boxes.conf.cpu().numpy()
            xyxys = r0.boxes.xyxy.cpu().numpy()

            dead_detected = False
            best_dead_conf = 0.0

            for cid, cf, xyxy in zip(cls_ids, confs, xyxys):
                name = self.model.names.get(int(cid), str(cid))
                cf = float(cf)

                overlay_label = name
                if name == self.cfg.DEAD_CLASS_NAME:
                    overlay_label = "malnutrisi"

                _draw_label_box(annotated, xyxy, overlay_label, cf)

                if name == self.cfg.DEAD_CLASS_NAME and cf >= self.cfg.DEAD_CONF:
                    dead_detected = True
                    best_dead_conf = max(best_dead_conf, cf)

            self.last_annotated_bgr = annotated

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

            # plants exist + not in malnutrisi state => normal
            if not self.dead_state:
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
        self._emit_status("stopped")

    def stop(self):
        self.running = False
        self.quit()
        self.wait()
