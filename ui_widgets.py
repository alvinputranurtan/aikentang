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

        self.title = QtWidgets.QLabel("STATUS TANAMAN")
        self.title.setAlignment(QtCore.Qt.AlignCenter)
        self.title.setStyleSheet("font-size:20px; font-weight:900; color:#111827;")
        layout.addWidget(self.title)

        # BADGE: kunci tinggi supaya UI tidak berubah-ubah
        self.badge = QtWidgets.QLabel("")
        self.badge.setAlignment(QtCore.Qt.AlignCenter)
        self.badge.setTextFormat(QtCore.Qt.PlainText)
        self.badge.setWordWrap(True)

        # KUNCI TINGGI BADGE (ubah sesuai selera)
        self.badge.setFixedHeight(110)

        # SizePolicy: tinggi fixed, lebar boleh expand
        self.badge.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        layout.addWidget(self.badge)

        # DETAIL: biar panel stabil, kasih minimum height + fixed policy
        self.detail = QtWidgets.QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        # KUNCI AREA DETAIL biar gak loncat (ubah sesuai selera)
        self.detail.setMinimumHeight(240)
        self.detail.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        layout.addWidget(self.detail)

        layout.addStretch(1)

        self.set_stopped()

    # ======================
    # Helpers style generator
    # ======================
    def _set_badge(self, text: str, bg: str, fg: str, font_size: int = 30):
        # Catatan: font_size bisa kamu samakan di semua status untuk paling stabil.
        self.badge.setText(text)
        self.badge.setStyleSheet(f"""
            QLabel {{
                font-size: {font_size}px;
                font-weight: 900;
                padding: 18px;
                border-radius: 16px;
                background: {bg};
                color: {fg};
            }}
        """)

    def _set_detail(self, text: str, color: str, font_size: int = 18, weight: int = 800):
        self.detail.setText(text)
        self.detail.setStyleSheet(f"""
            QLabel {{
                font-size: {font_size}px;
                font-weight: {weight};
                color: {color};
                line-height: 1.7;
            }}
        """)

    # ==========
    # States
    # ==========
    def set_stopped(self):
        self._set_badge("⏹️  MODEL BERHENTI", bg="#e5e7eb", fg="#111827", font_size=28)
        self._set_detail(
            "DETEKSI DIMATIKAN\n\n"
            "• Kamera & inferensi YOLO tidak berjalan\n"
            "• Tidak ada update status ke DB\n"
            "• Tidak ada notifikasi Telegram\n\n"
            "Tekan START untuk menjalankan kembali",
            color="#111827",
            font_size=18,
            weight=800
        )

    def set_normal(self):
        self._set_badge("✅  NORMAL", bg="#dcfce7", fg="#14532d", font_size=30)
        self._set_detail(
            "TANAMAN AMAN\n\n"
            "• Monitoring kamera aktif\n"
            "• Sistem nutrisi berjalan normal\n"
            "• Tidak ada malnutrisi terdeteksi",
            color="#14532d",
            font_size=20,
            weight=800
        )

    def set_malnutrisi(self):
        self._set_badge("⚠️  MALNUTRISI", bg="#fee2e2", fg="#7f1d1d", font_size=30)
        self._set_detail(
            "TERDETEKSI MALNUTRISI\n\n"
            "Segera lakukan tindakan:\n"
            "1. Cek pompa air (hidupkan)\n"
            "2. Cek pompa nutrisi (hidupkan)\n"
            "3. Periksa aliran air ke tanaman\n\n"
            "Notifikasi Telegram telah dikirim",
            color="#7f1d1d",
            font_size=20,
            weight=900
        )

    def set_no_plant(self):
        self._set_badge("ℹ️  TIDAK ADA TANAMAN\nTERDETEKSI", bg="#dbeafe", fg="#1e3a8a", font_size=26)
        self._set_detail(
            "TIDAK ADA OBJEK TANAMAN\n\n"
            "Kemungkinan penyebab:\n"
            "• Kamera tidak mengarah ke tanaman\n"
            "• Tanaman di luar frame\n"
            "• Pencahayaan terlalu gelap/terlalu terang\n"
            "• Model belum mengenali kelas tanaman pada kondisi ini",
            color="#1e3a8a",
            font_size=18,
            weight=800
        )
