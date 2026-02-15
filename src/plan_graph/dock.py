"""
Plan Graph dock: shows the hierarchy of what the AI did during an edit run.
Node click -> bridge -> Revert dialog -> restore project state (no UI redesign).
"""

import json
import os

from PyQt5.QtCore import QFileInfo, QObject, Qt, QUrl, pyqtSlot
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QDockWidget, QMessageBox, QSizePolicy, QWidget


class PlanGraphBridge(QObject):
    """Exposed to plan graph page. Node click -> Revert dialog -> load_project_state."""

    def __init__(self, dock: "PlanGraphDock", parent=None):
        super().__init__(parent)
        self._dock = dock

    @pyqtSlot(str)
    def onNodeClicked(self, step_id: str):
        if not step_id:
            return
        from plan_graph.storage import get_step
        from plan_graph.revert_dialog import RevertStepDialog

        rec = get_step(step_id)
        if not rec:
            return
        snapshot = rec.get("snapshot_before")
        if not snapshot:
            QMessageBox.information(
                self._dock,
                "Revert",
                "No snapshot saved for this step (e.g. from before revert was enabled).",
            )
            return
        dlg = RevertStepDialog(rec, self._dock)
        if dlg.exec_() != RevertStepDialog.Accepted:
            return
        try:
            from classes.app import get_app
            get_app().project.load_project_state(snapshot)
            from plan_graph import get_plan_builder
            pb = get_plan_builder()
            self._dock.set_plan_json(pb.get_plan_json_string())
        except Exception as e:
            QMessageBox.warning(self._dock, "Revert failed", str(e))


class PlanGraphDock(QDockWidget):
    """Dock that displays the edit plan graph (root -> branches -> steps)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dockPlanGraph")
        self.setWindowTitle("Plan Graph")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self._view = QWebEngineView(self)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setWidget(self._view)

        self._bridge = PlanGraphBridge(self, self)
        page = self._view.page()
        if page:
            channel = QWebChannel(page)
            channel.registerObject("flowcutPlanBridge", self._bridge)
            page.setWebChannel(channel)

        # Load UI from this package's ui/ folder
        ui_dir = os.path.join(os.path.dirname(__file__), "ui")
        index_path = os.path.join(ui_dir, "index.html")
        if os.path.isfile(index_path):
            base_url = QUrl.fromLocalFile(QFileInfo(index_path).absoluteFilePath())
            with open(index_path, "r", encoding="utf-8") as f:
                html = f.read()
            self._view.setHtml(html, base_url)
        else:
            self._view.setHtml(
                "<p>Plan graph UI not found (plan_graph/ui/index.html).</p>",
                QUrl(),
            )

    @pyqtSlot(str)
    def set_plan_json(self, json_str: str) -> None:
        """Update the graph with new plan JSON. Called when plan is updated or when response is ready."""
        if not json_str or not getattr(self._view, "page", None):
            return
        try:
            escaped = json.dumps(json_str)
        except Exception:
            escaped = json.dumps("null")
        self._view.page().runJavaScript("setPlanGraph(%s);" % escaped)
