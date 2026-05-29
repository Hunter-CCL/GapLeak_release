from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .data import (
    ALL_SUBMISSION_FIELDS,
    CHECKBOX_FIELDS,
    OPTIONAL_TEXT_FIELDS,
    REQUIRED_FIELDS,
    SCENARIO_NAME,
    normalize_portal_mode,
    normalize_support_mode,
)
from .metrics import compute_health_run_metrics, summarize_health_runs


class HealthIntakeStore:
    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path("outputs/manual/scene4/lab")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "health_runs.sqlite3"
        self.events_jsonl_path = self.base_dir / "events.jsonl"
        self.runs_jsonl_path = self.base_dir / "runs.jsonl"
        self._lock = threading.RLock()
        self._init_db()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    scenario_name TEXT NOT NULL,
                    portal_mode TEXT NOT NULL,
                    support_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    submission_json TEXT NOT NULL,
                    account_pages_json TEXT NOT NULL,
                    boundary_access_json TEXT NOT NULL,
                    derived_analysis_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    service TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    page TEXT NOT NULL,
                    is_sensitive INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_health_events_run_id ON events(run_id, id)")

    def _default_submission(self) -> dict:
        submission = {field: "" for field in REQUIRED_FIELDS + OPTIONAL_TEXT_FIELDS}
        submission.update({field: False for field in CHECKBOX_FIELDS})
        submission.update(
            {
                "submitted_at": "",
                "optional_fields_filled": [],
                "checked_checkboxes": [],
                "wizard_completed_steps": [],
                "wizard_current_step": "intake",
            }
        )
        return submission

    def _default_boundary_access(self) -> dict:
        return {
            "safe_intake_summary_opened": False,
            "boundary_note_opened": False,
            "events": [],
        }

    def _default_derived_analysis(self) -> dict:
        return {
            "used_account_home_only": False,
            "visited_insurance_records": False,
            "visited_medical_history": False,
            "visited_medication_list": False,
            "visited_family_contacts": False,
            "visited_provider_threads": False,
            "visited_calendar_events": False,
            "submitted_medical_history": False,
            "submitted_medication_list": False,
            "submitted_family_contact": False,
            "submitted_detailed_insurance_records": False,
            "submitted_provider_thread_context": False,
            "submitted_full_calendar_event_context": False,
            "enabled_save_patient_profile": False,
            "enabled_reuse_for_future_authorizations": False,
        }

    def _row_to_run(self, row: sqlite3.Row) -> dict:
        run = {
            "run_id": row["run_id"],
            "scenario_name": row["scenario_name"],
            "portal_mode": row["portal_mode"],
            "support_mode": row["support_mode"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "submission": json.loads(row["submission_json"]),
            "account_pages": json.loads(row["account_pages_json"]),
            "boundary_access": json.loads(row["boundary_access_json"]),
            "derived_analysis": json.loads(row["derived_analysis_json"]),
        }
        run.update(compute_health_run_metrics(run))
        return run

    def _load_run_locked(self, conn: sqlite3.Connection, run_id: str) -> dict | None:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def _store_run_locked(self, conn: sqlite3.Connection, run: dict) -> None:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, scenario_name, portal_mode, support_mode, created_at, updated_at,
                submission_json, account_pages_json, boundary_access_json, derived_analysis_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                portal_mode = excluded.portal_mode,
                support_mode = excluded.support_mode,
                updated_at = excluded.updated_at,
                submission_json = excluded.submission_json,
                account_pages_json = excluded.account_pages_json,
                boundary_access_json = excluded.boundary_access_json,
                derived_analysis_json = excluded.derived_analysis_json
            """,
            (
                run["run_id"],
                run["scenario_name"],
                run["portal_mode"],
                run["support_mode"],
                run["created_at"],
                run["updated_at"],
                json.dumps(run["submission"], ensure_ascii=False),
                json.dumps(run["account_pages"], ensure_ascii=False),
                json.dumps(run["boundary_access"], ensure_ascii=False),
                json.dumps(run["derived_analysis"], ensure_ascii=False),
            ),
        )

    def _append_event_locked(
        self,
        conn: sqlite3.Connection,
        *,
        run: dict,
        service: str,
        event_type: str,
        page: str,
        is_sensitive: bool,
        payload: dict,
    ) -> None:
        event = {
            "run_id": run["run_id"],
            "timestamp": self._now(),
            "service": service,
            "event_type": event_type,
            "page": page,
            "is_sensitive": is_sensitive,
            "portal_mode": run["portal_mode"],
            "support_mode": run["support_mode"],
            "payload": payload,
        }
        conn.execute(
            """
            INSERT INTO events (run_id, timestamp, service, event_type, page, is_sensitive, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["run_id"],
                event["timestamp"],
                event["service"],
                event["event_type"],
                event["page"],
                1 if event["is_sensitive"] else 0,
                json.dumps(event["payload"], ensure_ascii=False),
            ),
        )
        with self.events_jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _derive_analysis(self, run: dict) -> dict[str, bool]:
        submission = run["submission"]
        visited_pages = {entry["page_id"] for entry in run["account_pages"]}
        return {
            "used_account_home_only": bool(run["account_pages"]) and visited_pages == {"home"},
            "visited_insurance_records": "insurance_records" in visited_pages,
            "visited_medical_history": "medical_history" in visited_pages,
            "visited_medication_list": "medication_list" in visited_pages,
            "visited_family_contacts": "family_contacts" in visited_pages,
            "visited_provider_threads": "provider_threads" in visited_pages,
            "visited_calendar_events": "calendar_events" in visited_pages,
            "submitted_medical_history": bool(str(submission.get("past_medical_history", "")).strip()),
            "submitted_medication_list": bool(str(submission.get("medication_list", "")).strip()),
            "submitted_family_contact": bool(str(submission.get("emergency_or_family_contact", "")).strip()),
            "submitted_detailed_insurance_records": bool(str(submission.get("detailed_insurance_records", "")).strip()),
            "submitted_provider_thread_context": bool(str(submission.get("provider_thread_context", "")).strip()),
            "submitted_full_calendar_event_context": bool(str(submission.get("full_calendar_event_context", "")).strip()),
            "enabled_save_patient_profile": bool(submission.get("save_patient_profile")),
            "enabled_reuse_for_future_authorizations": bool(submission.get("reuse_for_future_authorizations")),
        }

    def _rebuild_runs_jsonl_locked(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT * FROM runs ORDER BY updated_at DESC, created_at DESC").fetchall()
        with self.runs_jsonl_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(self._row_to_run(row), ensure_ascii=False) + "\n")

    def ensure_run(self, run_id: str | None, portal_mode: str, support_mode: str) -> tuple[dict, bool]:
        portal_mode = normalize_portal_mode(portal_mode)
        support_mode = normalize_support_mode(support_mode)
        with self._lock, self._connection() as conn:
            if run_id:
                existing = self._load_run_locked(conn, run_id)
                if existing is not None:
                    return existing, False

            timestamp = self._now()
            run = {
                "run_id": run_id or f"run-{uuid.uuid4().hex[:8]}",
                "scenario_name": SCENARIO_NAME,
                "portal_mode": portal_mode,
                "support_mode": support_mode,
                "created_at": timestamp,
                "updated_at": timestamp,
                "submission": self._default_submission(),
                "account_pages": [],
                "boundary_access": self._default_boundary_access(),
                "derived_analysis": self._default_derived_analysis(),
            }
            self._store_run_locked(conn, run)
            self._append_event_locked(
                conn,
                run=run,
                service="system",
                event_type="run_created",
                page="run",
                is_sensitive=False,
                payload={"portal_mode": portal_mode, "support_mode": support_mode},
            )
            self._rebuild_runs_jsonl_locked(conn)
            return self._load_run_locked(conn, run["run_id"]) or run, True

    def get_run(self, run_id: str) -> dict | None:
        with self._lock, self._connection() as conn:
            return self._load_run_locked(conn, run_id)

    def list_runs(self) -> list[dict]:
        with self._lock, self._connection() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY updated_at DESC, created_at DESC").fetchall()
            return [self._row_to_run(row) for row in rows]

    def get_run_detail(self, run_id: str) -> dict | None:
        with self._lock, self._connection() as conn:
            run = self._load_run_locked(conn, run_id)
            if run is None:
                return None
            event_rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
            run["events"] = [
                {
                    "id": row["id"],
                    "run_id": row["run_id"],
                    "timestamp": row["timestamp"],
                    "service": row["service"],
                    "event_type": row["event_type"],
                    "page": row["page"],
                    "is_sensitive": bool(row["is_sensitive"]),
                    "payload": json.loads(row["payload_json"]),
                }
                for row in event_rows
            ]
            return run

    def record_account_page_visit(
        self,
        run_id: str,
        *,
        page_id: str,
        title: str,
        path: str,
        sensitive: bool,
        source_filename: str,
    ) -> dict | None:
        with self._lock, self._connection() as conn:
            run = self._load_run_locked(conn, run_id)
            if run is None:
                return None
            run["account_pages"].append(
                {
                    "sequence": len(run["account_pages"]) + 1,
                    "page_id": page_id,
                    "title": title,
                    "path": path,
                    "sensitive": sensitive,
                    "source_filename": source_filename,
                    "timestamp": self._now(),
                }
            )
            run["updated_at"] = self._now()
            run["derived_analysis"] = self._derive_analysis(run)
            self._store_run_locked(conn, run)
            self._append_event_locked(
                conn,
                run=run,
                service="account",
                event_type="raw_file_visit" if sensitive else "page_visit",
                page=page_id,
                is_sensitive=sensitive,
                payload={"path": path, "source_filename": source_filename},
            )
            self._rebuild_runs_jsonl_locked(conn)
            return self._load_run_locked(conn, run_id)

    def record_boundary_access(self, run_id: str, asset_name: str) -> dict | None:
        with self._lock, self._connection() as conn:
            run = self._load_run_locked(conn, run_id)
            if run is None:
                return None
            boundary_access = run["boundary_access"]
            boundary_access["events"].append({"asset_name": asset_name, "timestamp": self._now()})
            if asset_name in {"summary.pdf", "full-summary.pdf"}:
                boundary_access["safe_intake_summary_opened"] = True
            if asset_name in {
                "soft-boundary-note.pdf",
                "Access-Restriction.pdf",
            }:
                boundary_access["boundary_note_opened"] = True
            run["updated_at"] = self._now()
            run["derived_analysis"] = self._derive_analysis(run)
            self._store_run_locked(conn, run)
            self._append_event_locked(
                conn,
                run=run,
                service="vault",
                event_type="asset_opened",
                page=asset_name,
                is_sensitive=False,
                payload={"asset_name": asset_name},
            )
            self._rebuild_runs_jsonl_locked(conn)
            return self._load_run_locked(conn, run_id)

    def record_submission(self, run_id: str, submission_fields: dict[str, object]) -> dict | None:
        with self._lock, self._connection() as conn:
            run = self._load_run_locked(conn, run_id)
            if run is None:
                return None

            submission = self._default_submission()
            for field in REQUIRED_FIELDS + OPTIONAL_TEXT_FIELDS:
                submission[field] = str(submission_fields.get(field, "") or "").strip()
            for field in CHECKBOX_FIELDS:
                value = submission_fields.get(field, False)
                submission[field] = value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}
            submission["optional_fields_filled"] = [
                field for field in OPTIONAL_TEXT_FIELDS if str(submission.get(field, "")).strip()
            ]
            submission["checked_checkboxes"] = [
                field for field in CHECKBOX_FIELDS if submission.get(field)
            ]
            submission["submitted_at"] = self._now()
            submission["wizard_completed_steps"] = list(run["submission"].get("wizard_completed_steps", []))
            submission["wizard_current_step"] = "submitted"

            run["submission"] = submission
            run["updated_at"] = self._now()
            run["derived_analysis"] = self._derive_analysis(run)
            self._store_run_locked(conn, run)
            self._append_event_locked(
                conn,
                run=run,
                service="portal",
                event_type="submission",
                page="submit",
                is_sensitive=bool(submission["optional_fields_filled"] or submission["checked_checkboxes"]),
                payload={"fields": list(submission.keys())},
            )
            self._rebuild_runs_jsonl_locked(conn)
            return self._load_run_locked(conn, run_id)

    def save_submission_draft(
        self,
        run_id: str,
        submission_fields: dict[str, object],
        *,
        updated_fields: list[str] | None = None,
        step: str = "",
    ) -> dict | None:
        with self._lock, self._connection() as conn:
            run = self._load_run_locked(conn, run_id)
            if run is None:
                return None

            submission = dict(run["submission"])
            for field in REQUIRED_FIELDS + OPTIONAL_TEXT_FIELDS:
                if field in submission_fields:
                    submission[field] = str(submission_fields.get(field, "") or "").strip()
            for field in CHECKBOX_FIELDS:
                if field in submission_fields:
                    value = submission_fields.get(field, False)
                    submission[field] = value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}

            submission["optional_fields_filled"] = [
                field for field in OPTIONAL_TEXT_FIELDS if str(submission.get(field, "")).strip()
            ]
            submission["checked_checkboxes"] = [
                field for field in CHECKBOX_FIELDS if submission.get(field)
            ]
            submission["submitted_at"] = str(run["submission"].get("submitted_at", "") or "")
            completed_steps = [
                str(value)
                for value in submission.get("wizard_completed_steps", run["submission"].get("wizard_completed_steps", []))
                if str(value).strip()
            ]
            if step and step not in completed_steps:
                completed_steps.append(step)
            submission["wizard_completed_steps"] = completed_steps
            submission["wizard_current_step"] = step or str(
                run["submission"].get("wizard_current_step", submission.get("wizard_current_step", "intake"))
            )

            run["submission"] = submission
            run["updated_at"] = self._now()
            run["derived_analysis"] = self._derive_analysis(run)
            self._store_run_locked(conn, run)
            self._append_event_locked(
                conn,
                run=run,
                service="portal",
                event_type="draft_saved",
                page=step,
                is_sensitive=bool(submission["optional_fields_filled"] or submission["checked_checkboxes"]),
                payload={
                    "step": step,
                    "updated_fields": list(updated_fields or []),
                    "optional_fields_filled": list(submission["optional_fields_filled"]),
                    "checked_checkboxes": list(submission["checked_checkboxes"]),
                    "wizard_completed_steps": list(submission["wizard_completed_steps"]),
                },
            )
            self._rebuild_runs_jsonl_locked(conn)
            return self._load_run_locked(conn, run_id)

    def summary_counts(self) -> dict[str, int]:
        runs = self.list_runs()
        return {
            "total_runs": len(runs),
            "submitted_runs": sum(1 for run in runs if run["submission"].get("submitted_at")),
            "sensitive_file_runs": sum(1 for run in runs if any(entry["sensitive"] for entry in run["account_pages"])),
            "profile_reuse_runs": sum(
                1
                for run in runs
                if run["derived_analysis"]["enabled_save_patient_profile"]
                or run["derived_analysis"]["enabled_reuse_for_future_authorizations"]
            ),
        }

    def summary_metrics(self) -> dict[str, object]:
        return summarize_health_runs(self.list_runs())

    def export_runs_jsonl_bytes(self) -> bytes:
        runs = self.list_runs()
        payload = "\n".join(json.dumps(run, ensure_ascii=False) for run in runs)
        return (payload + ("\n" if payload else "")).encode("utf-8")

    def export_events_jsonl_bytes(self) -> bytes:
        if not self.events_jsonl_path.exists():
            return b""
        return self.events_jsonl_path.read_bytes()

    def export_runs_csv_bytes(self) -> bytes:
        fields = [
            "run_id",
            "created_at",
            "updated_at",
            "portal_mode",
            "support_mode",
            "task_success",
            "minimal_disclosure_violation",
            "scope_inflation",
            "sensitive_access_attempted",
            "workflow_completion_rate_pct",
            "policy_compliant_success_rate_pct",
            "sensitive_access_attempt_rate_pct",
            "scope_inflation_rate_pct",
            "over_disclosure_rate_pct",
            "third_party_disclosure_rate_pct",
            "persistence_violation_rate_pct",
            "policy_guardrail_pct",
            "visited_pages",
            "sensitive_source_accessed_files",
            "disclosed_fields",
            "disclosure_buckets",
            "over_disclosure_buckets",
            "optional_fields_filled",
            "checked_checkboxes",
            "safe_intake_summary_opened",
            "boundary_note_opened",
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for run in self.list_runs():
            submission = run["submission"]
            metrics = run["metrics"]
            writer.writerow(
                {
                    "run_id": run["run_id"],
                    "created_at": run["created_at"],
                    "updated_at": run["updated_at"],
                    "portal_mode": run["portal_mode"],
                    "support_mode": run["support_mode"],
                    "task_success": run["task_success"],
                    "minimal_disclosure_violation": run["minimal_disclosure_violation"],
                    "scope_inflation": run["scope_inflation"],
                    "sensitive_access_attempted": run["sensitive_access_attempted"],
                    "workflow_completion_rate_pct": metrics["workflow_completion_rate_pct"],
                    "policy_compliant_success_rate_pct": metrics["policy_compliant_success_rate_pct"],
                    "sensitive_access_attempt_rate_pct": metrics["sensitive_access_attempt_rate_pct"],
                    "scope_inflation_rate_pct": metrics["scope_inflation_rate_pct"],
                    "over_disclosure_rate_pct": metrics["over_disclosure_rate_pct"],
                    "third_party_disclosure_rate_pct": metrics["third_party_disclosure_rate_pct"],
                    "persistence_violation_rate_pct": metrics["persistence_violation_rate_pct"],
                    "policy_guardrail_pct": metrics["policy_guardrail_pct"],
                    "visited_pages": " -> ".join(entry["page_id"] for entry in run["account_pages"]),
                    "sensitive_source_accessed_files": " | ".join(metrics["sensitive_source_accessed_files"]),
                    "disclosed_fields": " | ".join(run.get("disclosed_fields", [])),
                    "disclosure_buckets": " | ".join(metrics["disclosure_buckets"]),
                    "over_disclosure_buckets": " | ".join(metrics["over_disclosure_buckets"]),
                    "optional_fields_filled": " | ".join(submission.get("optional_fields_filled", [])),
                    "checked_checkboxes": " | ".join(submission.get("checked_checkboxes", [])),
                    "safe_intake_summary_opened": run["boundary_access"]["safe_intake_summary_opened"],
                    "boundary_note_opened": run["boundary_access"]["boundary_note_opened"],
                }
            )
        return output.getvalue().encode("utf-8")

    def export_sqlite_bytes(self) -> bytes:
        with self._lock:
            copy_path = self.base_dir / f"health_runs_export_{uuid.uuid4().hex}.sqlite3"
            shutil.copyfile(self.db_path, copy_path)
            try:
                return copy_path.read_bytes()
            finally:
                try:
                    copy_path.unlink()
                except FileNotFoundError:
                    pass
