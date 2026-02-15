# SQLite persistence for plan graphs and plan_steps (per-tool records).
import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from classes.logger import log

# Max length for output_result to avoid huge blobs (JSON if safe)
OUTPUT_RESULT_MAX_LEN = 10000


def _migrate_plan_steps_columns(conn):
    """Add snapshot_before / label if table existed without them."""
    for col in ("label", "snapshot_before"):
        try:
            conn.execute("ALTER TABLE plan_steps ADD COLUMN %s TEXT" % col)
            conn.commit()
        except sqlite3.OperationalError:
            pass


def _db_path():
    from classes import info
    base = getattr(info, "USER_PATH", os.path.expanduser("~/.openshot_qt"))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "plan_history.db")


def _init_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edit_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            graph_json TEXT NOT NULL,
            breakdown_json TEXT,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plan_steps (
            step_id TEXT PRIMARY KEY,
            plan_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            timestamp REAL NOT NULL,
            input_args TEXT NOT NULL,
            output_result TEXT,
            status TEXT NOT NULL,
            label TEXT,
            snapshot_before TEXT,
            FOREIGN KEY (plan_id) REFERENCES edit_plans(id)
        )
    """)
    conn.commit()
    _migrate_plan_steps_columns(conn)


def create_plan(prompt: str) -> Optional[int]:
    """Create a new plan row and return plan_id. Call at start_plan."""
    try:
        path = _db_path()
        conn = sqlite3.connect(path)
        _init_schema(conn)
        created_at = time.time()
        cur = conn.execute(
            "INSERT INTO edit_plans (prompt, graph_json, breakdown_json, created_at) VALUES (?, ?, ?, ?)",
            (prompt or "", "{}", "{}", created_at),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        log.debug("Plan created: id=%s", row_id)
        return row_id
    except Exception as e:
        log.warning("Failed to create plan: %s", e)
        return None


def update_plan(plan_id: int, graph_json: Any, breakdown_json: Any) -> None:
    """Update plan row with final graph and breakdown. Call at end_plan."""
    try:
        path = _db_path()
        conn = sqlite3.connect(path)
        _init_schema(conn)
        conn.execute(
            "UPDATE edit_plans SET graph_json = ?, breakdown_json = ? WHERE id = ?",
            (json.dumps(graph_json, default=str) if graph_json else "{}",
             json.dumps(breakdown_json, default=str) if breakdown_json else "{}",
             plan_id),
        )
        conn.commit()
        conn.close()
        log.debug("Plan updated: id=%s", plan_id)
    except Exception as e:
        log.warning("Failed to update plan: %s", e)


def add_step(
    step_id: str,
    plan_id: int,
    branch: str,
    tool_name: str,
    input_args: str,
    output_result: str,
    status: str,
    label: str = "",
    snapshot_before: Optional[str] = None,
) -> None:
    """Persist one tool step. snapshot_before = project state before tool ran."""
    try:
        result_trunc = (output_result or "")[:OUTPUT_RESULT_MAX_LEN]
        snap = (snapshot_before or "")[:500000]  # cap 500k chars
        path = _db_path()
        conn = sqlite3.connect(path)
        _init_schema(conn)
        conn.execute(
            """INSERT OR REPLACE INTO plan_steps
               (step_id, plan_id, branch, tool_name, timestamp, input_args, output_result, status, label, snapshot_before)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (step_id, plan_id, branch, tool_name, time.time(), input_args or "{}", result_trunc, status, label or "", snap),
        )
        conn.commit()
        conn.close()
        log.debug("Step saved: step_id=%s", step_id)
    except Exception as e:
        log.warning("Failed to save step %s: %s", step_id, e)


def get_step(step_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a step record by step_id for edit dialog."""
    try:
        path = _db_path()
        if not os.path.isfile(path):
            return None
        conn = sqlite3.connect(path)
        _init_schema(conn)
        row = conn.execute(
            """SELECT step_id, plan_id, branch, tool_name, timestamp, input_args, output_result, status, label, snapshot_before
               FROM plan_steps WHERE step_id = ?""",
            (step_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "step_id": row[0],
            "plan_id": row[1],
            "branch": row[2],
            "tool_name": row[3],
            "timestamp": row[4],
            "input_args": row[5],
            "output_result": row[6],
            "status": row[7],
            "label": row[8] if len(row) > 8 else "",
            "snapshot_before": row[9] if len(row) > 9 else None,
        }
    except Exception as e:
        log.warning("Failed to get step %s: %s", step_id, e)
        return None


def update_step_inputs(step_id: str, input_args: str) -> bool:
    """Update stored input_args for a step. Returns True on success."""
    try:
        path = _db_path()
        conn = sqlite3.connect(path)
        _init_schema(conn)
        conn.execute("UPDATE plan_steps SET input_args = ? WHERE step_id = ?", (input_args or "{}", step_id))
        conn.commit()
        conn.close()
        log.debug("Step inputs updated: step_id=%s", step_id)
        return True
    except Exception as e:
        log.warning("Failed to update step %s: %s", step_id, e)
        return False


def save_plan(plan_builder):
    """Legacy: save plan at end (when not using create_plan/update_plan flow)."""
    try:
        plan = plan_builder.get_plan_json()
        if not plan:
            return None
        path = _db_path()
        conn = sqlite3.connect(path)
        _init_schema(conn)
        prompt = plan.get("description") or plan.get("prompt") or ""
        graph_json = json.dumps(plan, default=str)
        breakdown = plan_builder.get_breakdown()
        breakdown_json = json.dumps(breakdown, default=str)
        created_at = time.time()
        cur = conn.execute(
            "INSERT INTO edit_plans (prompt, graph_json, breakdown_json, created_at) VALUES (?, ?, ?, ?)",
            (prompt, graph_json, breakdown_json, created_at),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        log.debug("Plan saved: id=%s", row_id)
        return row_id
    except Exception as e:
        log.warning("Failed to save plan: %s", e)
        return None


def load_plan(plan_id):
    try:
        path = _db_path()
        if not os.path.isfile(path):
            return None
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT prompt, graph_json, breakdown_json, created_at FROM edit_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": plan_id,
            "prompt": row[0],
            "graph": json.loads(row[1]) if row[1] else None,
            "breakdown": json.loads(row[2]) if row[2] else {},
            "created_at": row[3],
        }
    except Exception as e:
        log.warning("Failed to load plan %s: %s", plan_id, e)
        return None


def list_plans(limit=50):
    try:
        path = _db_path()
        if not os.path.isfile(path):
            return []
        conn = sqlite3.connect(path)
        _init_schema(conn)
        rows = conn.execute(
            "SELECT id, prompt, created_at FROM edit_plans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [{"id": r[0], "prompt": (r[1] or "")[:200], "created_at": r[2]} for r in rows]
    except Exception as e:
        log.warning("Failed to list plans: %s", e)
        return []
