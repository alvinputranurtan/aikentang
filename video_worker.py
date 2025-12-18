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


class VideoWorker(QtCore.QThread):
    frame_updated = QtCore.pyqtSignal(QtGui.QImage)
    log_signal = QtCore.pyqtSignal(str)
    alert_signal = QtCore.pyqtSignal(bool)  # True=ALERT

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

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    def run(self):
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

        cap = cv2.VideoCapture(0)
        self.running = True
        self.alert_signal.emit(False)

        while self.running:
            ret, frame = cap.read()
            if not ret:
                continue

            frame = cv2.flip(frame, 1)

            results = self.model.predict(frame, verbose=False)
            r0 = results[0]
            annotated = r0.plot()
            self.last_annotated_bgr = annotated

            # ---- detect dead ----
            dead_detected = False
            best_dead_conf = 0.0

            if r0.boxes is not None and len(r0.boxes) > 0:
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

            # NORMAL -> DEAD trigger
            if (not self.dead_state) and (self.dead_hits >= self.cfg.DEAD_HITS_REQUIRED):
                self.dead_state = True
                self.alert_signal.emit(True)

                # DB set 0
                if (now - self.last_db_update_ts) >= self.cfg.DB_COOLDOWN_SEC:
                    try:
                        affected = set_current(self.cfg, self.cfg.DEVICE_ID, 0, 0, 0)
                        self._log(f"[DB] DEAD -> set current=0 (affected={affected})")
                        self.last_db_update_ts = now
                    except Exception as e:
                        self._log(f"[DB] ERROR set current=0: {e}")

                # Telegram snapshot (non-blocking)
                if self.cfg.telegram_enabled() and self.last_annotated_bgr is not None:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    caption = (
                        f"⚠️ DETEKSI DEAD\n"
                        f"Waktu: {ts}\n"
                        f"Device ID: {self.cfg.DEVICE_ID}\n"
                        f"dead_hits: {self.dead_hits}\n"
                        f"conf_best: {best_dead_conf:.2f}\n"
                        f"Action: set current=0"
                    )
                    ok, buf = cv2.imencode(".jpg", self.last_annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    if ok:
                        queued = self.tg.enqueue_photo(buf.tobytes(), caption)
                        self._log("[TG] queued snapshot" if queued else "[TG] queue full, skip")

            # DEAD -> RECOVER trigger
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
                    self.alert_signal.emit(False)

            # send frame to UI
            rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            img_qt = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
            self.frame_updated.emit(img_qt)

        cap.release()

    def stop(self):
        self.running = False
        self.quit()
        self.wait()
