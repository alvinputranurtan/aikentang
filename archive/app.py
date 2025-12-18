import sys
import os
import time
import cv2
import requests
import threading
import queue

from PyQt5 import QtWidgets, QtGui, QtCore
from ultralytics import YOLO
from dotenv import load_dotenv
import pymysql


# ===================== MODEL PATH =====================
PATH_MODEL_1 = "model_1.pt"
PATH_MODEL_2 = "model_2.pt"


# ===================== ENV / CONFIG =====================
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "")
DB_NAME = os.getenv("DB_NAME", "")
DB_USER = os.getenv("DB_USER", "")
DB_PASS = os.getenv("DB_PASS", "")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DEVICE_ID = int(os.getenv("DEVICE_ID", "3"))

DEAD_CLASS_NAME = os.getenv("DEAD_CLASS_NAME", "dead")
DEAD_CONF = float(os.getenv("DEAD_CONF", "0.60"))
DEAD_HITS_REQUIRED = int(os.getenv("DEAD_HITS_REQUIRED", "8"))
RECOVER_AFTER_SEC = int(os.getenv("RECOVER_AFTER_SEC", "30"))
DB_COOLDOWN_SEC = int(os.getenv("DB_COOLDOWN_SEC", "10"))

TG_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TG_COOLDOWN_SEC = int(os.getenv("TELEGRAM_COOLDOWN_SEC", "10"))


def tg_enabled() -> bool:
    return bool(TG_BOT_TOKEN) and bool(TG_CHAT_ID)


# ===================== TELEGRAM WORKER (NO FREEZE) =====================
class TelegramSender:
    """
    Worker thread untuk kirim Telegram agar tidak blocking thread video/UI.
    Ada cooldown internal (max 1 kirim per TG_COOLDOWN_SEC).
    """
    def __init__(self, token: str, chat_id: str, cooldown_sec: int = 10, queue_size: int = 5):
        self.token = token
        self.chat_id = chat_id
        self.cooldown_sec = cooldown_sec
        self.q: "queue.Queue[tuple]" = queue.Queue(maxsize=queue_size)
        self.last_send_ts = 0.0
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        if self.token and self.chat_id:
            self.thread.start()

    def stop(self):
        self.stop_event.set()

    def enqueue_photo(self, jpg_bytes: bytes, caption: str) -> bool:
        try:
            self.q.put_nowait(("photo", jpg_bytes, caption))
            return True
        except queue.Full:
            return False

    def _run(self):
        while not self.stop_event.is_set():
            try:
                kind, jpg_bytes, caption = self.q.get(timeout=0.5)
            except queue.Empty:
                continue

            # cooldown anti spam
            now = time.time()
            wait = (self.last_send_ts + self.cooldown_sec) - now
            if wait > 0:
                time.sleep(wait)

            try:
                url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
                requests.post(
                    url,
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"photo": ("snapshot.jpg", jpg_bytes, "image/jpeg")},
                    timeout=12,
                )
            except Exception:
                pass
            finally:
                self.last_send_ts = time.time()
                self.q.task_done()


TG_SENDER = TelegramSender(TG_BOT_TOKEN, TG_CHAT_ID, TG_COOLDOWN_SEC)
if tg_enabled():
    TG_SENDER.start()


# ===================== DB HELPERS =====================
def db_connect():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        port=DB_PORT,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def db_get_threshold(device_id: int):
    sql = """
    SELECT
      JSON_UNQUOTE(JSON_EXTRACT(data_configuration, '$.device_configuration.threshold.n')) AS tn,
      JSON_UNQUOTE(JSON_EXTRACT(data_configuration, '$.device_configuration.threshold.p')) AS tp,
      JSON_UNQUOTE(JSON_EXTRACT(data_configuration, '$.device_configuration.threshold.k')) AS tk
    FROM configurations
    WHERE device_id = %s
      AND is_active = 1
      AND deleted_at IS NULL
    ORDER BY id DESC
    LIMIT 1;
    """
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (device_id,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Threshold tidak ditemukan. Pastikan configurations ada & is_active=1.")
            tn = int(row["tn"]) if row["tn"] is not None else 0
            tp = int(row["tp"]) if row["tp"] is not None else 0
            tk = int(row["tk"]) if row["tk"] is not None else 0
            return {"n": tn, "p": tp, "k": tk}
    finally:
        conn.close()


def db_set_current(device_id: int, n: int, p: int, k: int):
    sql = """
    UPDATE configurations
    SET data_configuration =
      JSON_SET(
        data_configuration,
        '$.device_configuration.current.n', %s,
        '$.device_configuration.current.p', %s,
        '$.device_configuration.current.k', %s
      ),
      updated_at = NOW()
    WHERE device_id = %s
      AND is_active = 1
      AND deleted_at IS NULL;
    """
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (n, p, k, device_id))
            return cur.rowcount
    finally:
        conn.close()


# ===================== VIDEO THREAD =====================
class VideoThread(QtCore.QThread):
    frame_updated = QtCore.pyqtSignal(QtGui.QImage)
    log_signal = QtCore.pyqtSignal(str)
    status_signal = QtCore.pyqtSignal(str)  # status text di UI (aman / mati + instruksi)

    def __init__(self, model: YOLO):
        super().__init__()
        self.model = model
        self.running = False

        # state machine
        self.dead_hits = 0
        self.dead_state = False
        self.last_dead_ts = 0.0
        self.last_db_update_ts = 0.0

        self.threshold = {"n": 0, "p": 0, "k": 0}

        # snapshot frame terakhir (annotated)
        self.last_annotated_bgr = None

    def _emit_log(self, msg: str):
        self.log_signal.emit(msg)

    def run(self):
        # load threshold
        try:
            self.threshold = db_get_threshold(DEVICE_ID)
            self._emit_log(f"[DB] Threshold loaded: {self.threshold}")
        except Exception as e:
            self._emit_log(f"[DB] ERROR load threshold: {e}")

        # log model classes
        try:
            self._emit_log(f"[MODEL] classes: {self.model.names}")
        except Exception:
            pass

        self._emit_log(
            f"[CFG] DEAD_CLASS_NAME='{DEAD_CLASS_NAME}', DEAD_CONF={DEAD_CONF}, "
            f"DEAD_HITS_REQUIRED={DEAD_HITS_REQUIRED}, RECOVER_AFTER_SEC={RECOVER_AFTER_SEC}, "
            f"DB_COOLDOWN_SEC={DB_COOLDOWN_SEC}, TG_ENABLED={tg_enabled()}, TG_COOLDOWN_SEC={TG_COOLDOWN_SEC}"
        )

        self.cap = cv2.VideoCapture(0)
        self.running = True

        # status awal
        self.status_signal.emit("✅ TANAMAN AMAN")

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                continue

            frame = cv2.flip(frame, 1)

            results = self.model.predict(frame, verbose=False)
            r0 = results[0]
            annotated = r0.plot()  # BGR
            self.last_annotated_bgr = annotated

            # ===== deteksi dead (ambil best_conf) =====
            dead_detected = False
            best_dead_conf = 0.0

            if r0.boxes is not None and len(r0.boxes) > 0:
                cls_ids = r0.boxes.cls.cpu().numpy().astype(int)
                confs = r0.boxes.conf.cpu().numpy()

                for cid, cf in zip(cls_ids, confs):
                    name = self.model.names.get(int(cid), str(cid))
                    cf = float(cf)
                    if name == DEAD_CLASS_NAME and cf >= DEAD_CONF:
                        dead_detected = True
                        if cf > best_dead_conf:
                            best_dead_conf = cf

            now = time.time()

            # update last_dead_ts bila ada dead
            if dead_detected:
                self.last_dead_ts = now

            # debounce hits
            if dead_detected:
                self.dead_hits += 1
            else:
                self.dead_hits = max(0, self.dead_hits - 1)

            # ===== status text UI =====
            if self.dead_state:
                self.status_signal.emit(
                    "⚠️ ADA TANAMAN MATI, COBA LAKUKAN INI:\n"
                    "1. cek pompa air, hidupkan\n"
                    "2. cek pompa nutrisi, hidupkan"
                )
            else:
                self.status_signal.emit("✅ TANAMAN AMAN")

            # ===== transisi NORMAL -> DEAD =====
            if (not self.dead_state) and (self.dead_hits >= DEAD_HITS_REQUIRED):
                self.dead_state = True
                self.last_dead_ts = now

                # DB set current=0
                if (now - self.last_db_update_ts) >= DB_COOLDOWN_SEC:
                    try:
                        affected = db_set_current(DEVICE_ID, 0, 0, 0)
                        self._emit_log(f"[DB] DEAD -> set current=0, affected={affected}")
                        self.last_db_update_ts = now
                    except Exception as e:
                        self._emit_log(f"[DB] ERROR set current=0: {e}")

                # Telegram snapshot (enqueue, non-blocking)
                if tg_enabled() and self.last_annotated_bgr is not None:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    caption = (
                        f"⚠️ DETEKSI DEAD\n"
                        f"Waktu: {ts}\n"
                        f"Device ID: {DEVICE_ID}\n"
                        f"Kondisi: DEAD\n"
                        f"dead_hits: {self.dead_hits}\n"
                        f"conf_best: {best_dead_conf:.2f}\n"
                        f"Action: set current=0"
                    )
                    ok, buf = cv2.imencode(".jpg", self.last_annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    if ok:
                        queued = TG_SENDER.enqueue_photo(buf.tobytes(), caption)
                        if queued:
                            self._emit_log("[TG] queued snapshot (sendPhoto)")
                        else:
                            self._emit_log("[TG] queue full, skip snapshot")
                    else:
                        self._emit_log("[TG] encode jpg failed")

            # ===== transisi DEAD -> RECOVER =====
            if self.dead_state:
                dead_absent_for = now - self.last_dead_ts
                # log countdown tiap 1 detik (biar gak spam)
                # (optional) boleh dimatikan kalau kebanyakan
                # if int(dead_absent_for) % 5 == 0:
                #     self._emit_log(f"[RECOVER] no-dead for {dead_absent_for:.1f}s")

                if dead_absent_for >= RECOVER_AFTER_SEC:
                    n = int(self.threshold.get("n", 0)) + 1
                    p = int(self.threshold.get("p", 0)) + 1
                    k = int(self.threshold.get("k", 0)) + 1

                    if (now - self.last_db_update_ts) >= DB_COOLDOWN_SEC:
                        try:
                            affected = db_set_current(DEVICE_ID, n, p, k)
                            self._emit_log(
                                f"[DB] RECOVER ({RECOVER_AFTER_SEC}s no-dead) -> set current=threshold+1 "
                                f"({n},{p},{k}), affected={affected}"
                            )
                            self.last_db_update_ts = now
                        except Exception as e:
                            self._emit_log(f"[DB] ERROR set current=threshold+1: {e}")

                    self.dead_state = False
                    self.dead_hits = 0

            # ===== emit frame to UI (tanpa debug overlay) =====
            rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            img_qt = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
            self.frame_updated.emit(img_qt)

        self.cap.release()

    def stop(self):
        self.running = False
        self.quit()
        self.wait()


# ===================== RESPONSIVE VIDEO LABEL =====================
class ResponsiveVideoLabel(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setStyleSheet("background-color: #111; border-radius: 14px;")
        self._pix = None
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def setImage(self, pixmap: QtGui.QPixmap):
        self._pix = pixmap
        self._updateScaled()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updateScaled()

    def _updateScaled(self):
        if self._pix is None:
            return
        scaled = self._pix.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        super().setPixmap(scaled)


# ===================== UI APP =====================
class App(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Deteksi Kentang - PyQt5 + YOLO + DB Sync + Telegram")
        self.resize(1100, 720)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QtWidgets.QLabel("Deteksi Kentang (Real-Time) + Update DB + Telegram snapshot")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        # STATUS TEXT (Aman / Mati + instruksi)
        self.status_label = QtWidgets.QLabel("✅ TANAMAN AMAN")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 700;
                padding: 10px;
                border-radius: 12px;
                background: #f3f4f6;
            }
        """)
        root.addWidget(self.status_label)

        # VIDEO (RESPONSIVE)
        self.video_label = ResponsiveVideoLabel()
        root.addWidget(self.video_label, stretch=1)

        # LOG (diperkecil)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(120)  # <- diperkecil
        self.log_box.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        root.addWidget(self.log_box)

        # CONTROL ROW
        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(10)

        controls.addWidget(QtWidgets.QLabel("Umur Tanaman (hari):"))

        self.umur_input = QtWidgets.QSpinBox()
        self.umur_input.setRange(0, 100)
        self.umur_input.setValue(10)
        self.umur_input.setFixedWidth(120)
        self.umur_input.setStyleSheet("font-size: 14px; padding: 4px;")
        controls.addWidget(self.umur_input)

        controls.addStretch(1)

        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.setStyleSheet("background:#16a34a;color:white;font-size:14px;padding:10px;border-radius:10px;")
        self.start_btn.clicked.connect(self.start_camera)
        controls.addWidget(self.start_btn)

        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setStyleSheet("background:#dc2626;color:white;font-size:14px;padding:10px;border-radius:10px;")
        self.stop_btn.clicked.connect(self.stop_camera)
        controls.addWidget(self.stop_btn)

        root.addLayout(controls)

        self.thread = None

        # log env singkat
        self.log(f"[ENV] DEVICE_ID={DEVICE_ID}, DB_HOST={DB_HOST}, DB_NAME={DB_NAME}")
        self.log(f"[ENV] DEAD_CLASS_NAME='{DEAD_CLASS_NAME}', DEAD_CONF={DEAD_CONF}")
        self.log(f"[ENV] TG_ENABLED={tg_enabled()}, TG_COOLDOWN_SEC={TG_COOLDOWN_SEC}")

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"{ts} {msg}")
        # auto scroll to bottom
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def set_status(self, text: str):
        self.status_label.setText(text)
        # warn styling kalau ada mati
        if text.startswith("⚠️"):
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 16px;
                    font-weight: 800;
                    padding: 10px;
                    border-radius: 12px;
                    background: #fee2e2;
                    color: #7f1d1d;
                }
            """)
        else:
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 16px;
                    font-weight: 800;
                    padding: 10px;
                    border-radius: 12px;
                    background: #dcfce7;
                    color: #14532d;
                }
            """)

    def load_model(self):
        umur = self.umur_input.value()
        if umur <= 15:
            path = PATH_MODEL_1 if os.path.exists(PATH_MODEL_1) else "yolov8n.pt"
        else:
            path = PATH_MODEL_2 if os.path.exists(PATH_MODEL_2) else "yolov8s.pt"
        self.log(f"[INFO] Loading model: {path}")
        return YOLO(path)

    def start_camera(self):
        if self.thread and self.thread.running:
            return
        model = self.load_model()
        self.thread = VideoThread(model)
        self.thread.frame_updated.connect(self.update_image)
        self.thread.log_signal.connect(self.log)
        self.thread.status_signal.connect(self.set_status)
        self.thread.start()

    def stop_camera(self):
        if self.thread:
            self.thread.stop()
            self.log("[INFO] Stopped.")

    def update_image(self, img_qt: QtGui.QImage):
        pix = QtGui.QPixmap.fromImage(img_qt)
        self.video_label.setImage(pix)

    def closeEvent(self, event):
        # stop thread + telegram worker
        try:
            if self.thread:
                self.thread.stop()
        except Exception:
            pass
        try:
            TG_SENDER.stop()
        except Exception:
            pass
        super().closeEvent(event)


# ===================== RUN =====================
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = App()
    win.show()
    sys.exit(app.exec_())
