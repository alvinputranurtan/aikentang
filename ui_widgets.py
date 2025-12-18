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

        self.badge = QtWidgets.QLabel("")
        self.badge.setAlignment(QtCore.Qt.AlignCenter)
        self.badge.setMinimumHeight(80)
        layout.addWidget(self.badge)

        self.detail = QtWidgets.QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        layout.addWidget(self.detail)

        layout.addStretch(1)

        self.set_normal()

    def set_normal(self):
        self.badge.setText("✅  NORMAL")
        self.badge.setStyleSheet("""
            QLabel {
                font-size: 34px;
                font-weight: 900;
                padding: 18px;
                border-radius: 16px;
                background: #dcfce7;
                color: #14532d;
            }
        """)
        self.detail.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: 800;
                color: #14532d;
                line-height: 1.7;
            }
        """)
        self.detail.setText(
            "TANAMAN AMAN\n\n"
            "• Monitoring kamera aktif\n"
            "• Sistem nutrisi berjalan normal\n"
            "• Tidak ada tanaman mati terdeteksi"
        )

    def set_alert(self):
        self.badge.setText("⚠️  ALERT")
        self.badge.setStyleSheet("""
            QLabel {
                font-size: 34px;
                font-weight: 900;
                padding: 18px;
                border-radius: 16px;
                background: #fee2e2;
                color: #7f1d1d;
            }
        """)
        self.detail.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: 900;
                color: #7f1d1d;
                line-height: 1.7;
            }
        """)
        self.detail.setText(
            "TERDETEKSI TANAMAN MATI\n\n"
            "Segera lakukan tindakan:\n"
            "1. Cek pompa air (hidupkan)\n"
            "2. Cek pompa nutrisi (hidupkan)\n"
            "3. Periksa aliran air ke tanaman\n\n"
            "Notifikasi Telegram telah dikirim"
        )
