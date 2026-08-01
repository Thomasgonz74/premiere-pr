"""Cancellable countdown dialog shown while an auto-shutdown is pending.

This widget is self-contained and does not wire itself to
AutoShutdownService -- whoever owns MainWindow-level construction should
connect `AutoShutdownService.shutdown_countdown_started` to show an instance
of this dialog, and connect its `cancelled` signal (or the "Annuler" button
directly) to `AutoShutdownService.cancel_shutdown()`.
"""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

_ACTION_LABELS = {
    "shutdown": "L'ordinateur va s'éteindre",
    "hibernate": "L'ordinateur va se mettre en veille prolongée",
}


class ShutdownCountdownDialog(QDialog):
    """A small non-modal-friendly countdown dialog: ticks down once per
    second via its own QTimer and emits `cancelled` if the user clicks
    "Annuler" before it reaches zero."""

    cancelled = Signal()

    def __init__(self, delay_seconds: int, action: str = "shutdown", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extinction automatique")
        self._remaining = max(0, delay_seconds)

        layout = QVBoxLayout(self)

        self.message_label = QLabel(_ACTION_LABELS.get(action, _ACTION_LABELS["shutdown"]), self)
        layout.addWidget(self.message_label)

        self.countdown_label = QLabel(self)
        layout.addWidget(self.countdown_label)
        self._update_label()

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Annuler", self)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)

    def _update_label(self) -> None:
        self.countdown_label.setText(f"Tous les téléchargements sont terminés. Extinction dans {self._remaining} s.")

    def _on_tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self._remaining = 0
            self._update_label()
            self.accept()
            return
        self._update_label()

    def _on_cancel_clicked(self) -> None:
        self._timer.stop()
        self.cancelled.emit()
        self.reject()
