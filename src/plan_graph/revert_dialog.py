"""Simple dialog: Revert to this step (label, timestamp, Revert / Cancel)."""

from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout


def _format_timestamp(ts):
    if ts is None:
        return ""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


class RevertStepDialog(QDialog):
    """Small native dialog: step label, timestamp, [Revert to this step] [Cancel]."""

    def __init__(self, step_record: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Revert to step")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Step:", QLabel(step_record.get("label") or step_record.get("tool_name") or "—"))
        form.addRow("When:", QLabel(_format_timestamp(step_record.get("timestamp"))))
        layout.addLayout(form)
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Revert to this step")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
