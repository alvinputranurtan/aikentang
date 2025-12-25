# ui_widgets.py
from PyQt5 import QtWidgets, QtGui, QtCore


class ResponsiveVideoLabel(QtWidgets.QLabel):
    """
    Video label responsif.
    Default: KeepAspectRatio (tidak crop).
    Kalau mau minim bar hitam (dengan crop sedikit), ganti ke KeepAspectRatioByExpanding.
    """
    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setStyleSheet("background:#000;border-radius:16px;")
        self._pix = None
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def setImage(self, img_qt: QtGui.QImage):
        self._pix = QtGui.QPixmap.fromImage(img_qt)
        self._updateScaled()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._updateScaled()

    def _updateScaled(self):
        if self._pix is None:
            return
        scaled = self._pix.scaled(
            self.size(),
            QtCore.Qt.KeepAspectRatio,  # or KeepAspectRatioByExpanding
            QtCore.Qt.SmoothTransformation
        )
        self.setPixmap(scaled)


class StatusPanel(QtWidgets.QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("rightPanel")
        self.setStyleSheet("""
            QFrame#rightPanel {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 18px;
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ===== TITLE =====
        self.title = QtWidgets.QLabel("STATUS TANAMAN")
        self.title.setAlignment(QtCore.Qt.AlignCenter)
        self.title.setStyleSheet("font-size:20px; font-weight:900; color:#111827;")
        self.title.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.title)

        # ===== BADGE (FIXED HEIGHT) =====
        self.badge = QtWidgets.QLabel("")
        self.badge.setAlignment(QtCore.Qt.AlignCenter)
        self.badge.setWordWrap(True)  # penting untuk teks panjang / multiline
        self.badge.setMinimumHeight(110)
        self.badge.setMaximumHeight(110)  # kunci tinggi supaya tidak berubah-ubah
        self.badge.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.badge)

        # ===== DETAIL (SCROLLABLE, NEVER CUT OFF) =====
        self.detail = QtWidgets.QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self.detail.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        self.detail_scroll = QtWidgets.QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.detail_scroll.setWidget(self.detail)
        self.detail_scroll.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.detail_scroll.setMinimumHeight(220)  # biar “tidak ada tanaman” nyaman dibaca

        layout.addWidget(self.detail_scroll)

        self.set_stopped()

    # ===== Helpers: apply style without changing geometry =====
    def _set_badge_style(self, font_px: int, bg: str, fg: str):
        # line-height di Qt stylesheet tidak selalu konsisten, jadi fokus ke padding + fixed height
        self.badge.setStyleSheet(f"""
            QLabel {{
                font-size: {font_px}px;
                font-weight: 900;
                padding: 14px;
                border-radius: 16px;
                background: {bg};
                color: {fg};
            }}
        """)

    def _set_detail_style(self, font_px: int, fg: str, weight: int = 800):
        self.detail.setStyleSheet(f"""
            QLabel {{
                font-size: {font_px}px;
                font-weight: {weight};
                color: {fg};
            }}
        """)

    # ===== States =====
    def set_stopped(self):
        self.badge.setText("⏹️  MODEL BERHENTI")
        self._set_badge_style(font_px=26, bg="#ffffff", fg="#111827")
        self._set_detail_style(font_px=18, fg="#111827", weight=800)
        self.detail.setText(
            "DETEKSI DIMATIKAN\n\n"
            "• Kamera & inferensi YOLO tidak berjalan\n"
            "• Tidak ada update status ke DB\n"
            "• Tidak ada notifikasi Telegram\n\n"
            "Tekan START untuk menjalankan kembali"
        )

    def set_normal(self):
        self.badge.setText("✅  NORMAL")
        self._set_badge_style(font_px=32, bg="#ffffff", fg="#14532d")
        self._set_detail_style(font_px=20, fg="#14532d", weight=800)
        self.detail.setText(
            "TANAMAN AMAN\n\n"
            "• Monitoring kamera aktif\n"
            "• Sistem nutrisi berjalan normal\n"
            "• Tidak ada malnutrisi terdeteksi"
        )

    def set_malnutrisi(self):
        self.badge.setText("⚠️  MALNUTRISI")
        self._set_badge_style(font_px=30, bg="#ffffff", fg="#7f1d1d")
        self._set_detail_style(font_px=20, fg="#7f1d1d", weight=900)
        self.detail.setText(
            "TERDETEKSI MALNUTRISI\n\n"
            "Segera lakukan tindakan:\n"
            "1. Cek pompa air (hidupkan)\n"
            "2. Cek pompa nutrisi (hidupkan)\n"
            "3. Periksa aliran air ke tanaman\n\n"
            "Notifikasi Telegram telah dikirim"
        )

    def set_no_plant(self):
        # badge tetap fixed height, tapi teks panjang aman karena wordWrap aktif
        self.badge.setText("ℹ️  TIDAK ADA TANAMAN\nTERDETEKSI")
        self._set_badge_style(font_px=24, bg="#dbeafe", fg="#1e3a8a")
        self._set_detail_style(font_px=18, fg="#1e3a8a", weight=800)
        self.detail.setText(
            "TIDAK ADA OBJEK TANAMAN\n\n"
            "Kemungkinan penyebab:\n"
            "• Kamera tidak mengarah ke tanaman\n"
            "• Tanaman di luar frame\n"
            "• Pencahayaan terlalu gelap/terlalu terang\n"
            "• Model belum mengenali kelas tanaman pada kondisi ini"
        )
