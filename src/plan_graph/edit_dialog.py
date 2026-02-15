"""Simple edit dialog for a plan step: edit input_args (JSON)."""

import json

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class StepEditDialog(QDialog):
    """Modal to edit a step's input_args (JSON). Save updates DB and builder, then caller refreshes graph."""

    def __init__(self, step_record: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit step inputs")
        self.step_record = step_record
        self._layout = QVBoxLayout(self)

        form = QFormLayout()
        form.addRow("Step ID:", QLabel(step_record.get("step_id", "")))
        form.addRow("Tool:", QLabel(step_record.get("tool_name", "")))
        form.addRow("Branch:", QLabel(step_record.get("branch", "")))
        self._args_edit = QPlainTextEdit()
        args = step_record.get("input_args") or "{}"
        if isinstance(args, str):
            try:
                args = json.loads(args)
                args = json.dumps(args, indent=2)
            except Exception:
                pass
        self._args_edit.setPlainText(args)
        self._args_edit.setMinimumHeight(120)
        form.addRow("Input args (JSON):", self._args_edit)
        self._layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self._buttons.accepted.connect(self._on_save)
        self._buttons.rejected.connect(self.reject)
        self._layout.addWidget(self._buttons)

    def _on_save(self):
        text = self._args_edit.toPlainText().strip() or "{}"
        try:
            json.loads(text)
        except Exception:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid JSON", "Input args must be valid JSON.")
            return
        self.saved_args_json = text
        self.accept()

    def get_saved_args_json(self) -> str:
        return getattr(self, "saved_args_json", "")
