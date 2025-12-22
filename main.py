import sys
import time
from PyQt5 import QtWidgets, QtCore

from config import AppConfig
from ui_widgets import ResponsiveVideoLabel, StatusPanel
from telegram_sender import TelegramSender
from video_worker import VideoWorker, load_model_for_age


class MainWindow(QtWidgets.QWidget):
    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self.worker = None

        self.setWindowTitle("Deteksi Kentang - PyQt5 + YOLO + DB + Telegram")
        self.resize(1200, 780)

        # Telegram worker (thread)
        self.tg = TelegramSender(cfg)
        self.tg.start()

        self._build_ui()
        self._connect_signals()

        self.log(f"[ENV] DEVICE_ID={cfg.DEVICE_ID}, DB={cfg.DB_HOST}/{cfg.DB_NAME}, TG={cfg.telegram_enabled()}")

    # ---------- UI ----------
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self.title = QtWidgets.QLabel("Deteksi Kentang (Real-Time) + Update DB + Telegram snapshot")
        self.title.setAlignment(QtCore.Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(self.title)

        main_row = QtWidgets.QHBoxLayout()
        main_row.setSpacing(12)

        self.video = ResponsiveVideoLabel()
        main_row.addWidget(self.video, stretch=3)

        self.status_panel = StatusPanel()
        main_row.addWidget(self.status_panel, stretch=1)

        root.addLayout(main_row, stretch=1)

        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(130)
        self.log_box.setStyleSheet("font-family: Consolas; font-size: 11px;")
        root.addWidget(self.log_box)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(10)

        controls.addWidget(QtWidgets.QLabel("Umur Tanaman (hari):"))
        self.umur = QtWidgets.QSpinBox()
        self.umur.setRange(0, 120)
        self.umur.setValue(10)
        self.umur.setFixedWidth(120)
        self.umur.setStyleSheet("font-size: 14px; padding: 4px;")
        controls.addWidget(self.umur)

        controls.addStretch(1)

        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_start.setStyleSheet("background:#16a34a;color:white;font-size:14px;padding:10px 16px;border-radius:10px;")
        controls.addWidget(self.btn_start)

        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setStyleSheet("background:#dc2626;color:white;font-size:14px;padding:10px 16px;border-radius:10px;")
        controls.addWidget(self.btn_stop)

        root.addLayout(controls)

        self._set_running(False)

    def _connect_signals(self):
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)

    def _set_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.umur.setEnabled(not running)

    # ---------- Logging ----------
    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"{ts} {msg}")
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------- Actions ----------
    def start(self):
        if self.worker and self.worker.running:
            return

        try:
            model = load_model_for_age(self.cfg, self.umur.value())
            self.log(f"[INFO] Model loaded (umur={self.umur.value()} hari)")
        except Exception as e:
            self.log(f"[ERR] Failed to load model: {e}")
            return

        self.worker = VideoWorker(self.cfg, model, self.tg)
        self.worker.frame_updated.connect(self.video.setImage)
        self.worker.log_signal.connect(self.log)
        self.worker.alert_signal.connect(self.on_alert)

        self._set_running(True)
        self.worker.start()

    def stop(self):
        if self.worker:
            try:
                self.worker.stop()
            except Exception as e:
                self.log(f"[WARN] Stop worker error: {e}")
            self.worker = None

        self._set_running(False)
        self.log("[INFO] Stopped.")

    def on_alert(self, is_alert: bool):
        if is_alert:
            self.status_panel.set_alert()
        else:
            self.status_panel.set_normal()

    def closeEvent(self, event):
        try:
            self.stop()
        except Exception:
            pass
        try:
            self.tg.stop()
        except Exception:
            pass
        super().closeEvent(event)


if __name__ == "__main__":
    cfg = AppConfig()
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(cfg)
    win.show()
    sys.exit(app.exec_())
