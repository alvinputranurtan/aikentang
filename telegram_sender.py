import time
import threading
import queue
import requests
from typing import Optional
from config import AppConfig

class TelegramSender:
    def __init__(self, cfg: AppConfig, queue_size: int = 5):
        self.cfg = cfg
        self.q: "queue.Queue[tuple[str, bytes, str]]" = queue.Queue(maxsize=queue_size)
        self.last_send_ts = 0.0
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self):
        if not self.cfg.telegram_enabled():
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def enqueue_photo(self, jpg_bytes: bytes, caption: str) -> bool:
        if not self.cfg.telegram_enabled():
            return False
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

            now = time.time()
            wait = (self.last_send_ts + self.cfg.TG_COOLDOWN_SEC) - now
            if wait > 0:
                time.sleep(wait)

            try:
                url = f"https://api.telegram.org/bot{self.cfg.TG_BOT_TOKEN}/sendPhoto"
                requests.post(
                    url,
                    data={"chat_id": self.cfg.TG_CHAT_ID, "caption": caption},
                    files={"photo": ("snapshot.jpg", jpg_bytes, "image/jpeg")},
                    timeout=12,
                )
            except Exception:
                pass
            finally:
                self.last_send_ts = time.time()
                self.q.task_done()
