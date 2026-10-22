import importlib
import sys
import tempfile
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from fastapi import Response
from pydantic.warnings import UnsupportedFieldAttributeWarning


ROOT = Path(__file__).resolve().parents[3]


def import_oms3_main():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    sys.path.insert(0, str(ROOT / "OMS3"))
    try:
        return importlib.import_module("app.main")
    finally:
        sys.path.pop(0)


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class FakeReportTaskStorage:
    def __init__(self):
        self.tasks = {}

    def migrate(self):
        return None

    def check(self):
        return None

    def create_or_get(self, task, idempotency_key):
        for item in self.tasks.values():
            if idempotency_key and item.get("idempotencyKey") == idempotency_key:
                return item, False
        task = {**task, "idempotencyKey": idempotency_key, "workerId": None, "leaseUntil": None}
        self.tasks[task["id"]] = task
        return task, True

    def get(self, task_id):
        return self.tasks.get(task_id)

    def claim(self, task_id, worker_id, lease_until):
        task = self.tasks.get(task_id)
        if not task or task["status"] != "queued":
            return None
        now = datetime.now(timezone.utc)
        task.update({"status": "running", "workerId": worker_id, "startedAt": now, "leaseUntil": lease_until, "updatedAt": now})
        return task

    def update_running(self, task_id, worker_id, values):
        task = self.tasks.get(task_id)
        if not task or task["status"] != "running" or task["workerId"] != worker_id:
            return None
        task.update(values)
        task["updatedAt"] = datetime.now(timezone.utc)
        return task

    def update(self, task_id, values):
        task = self.tasks.get(task_id)
        if not task:
            return None
        task.update(values)
        task["updatedAt"] = datetime.now(timezone.utc)
        return task

    def cancel(self, task_id):
        task = self.tasks.get(task_id)
        if not task or task["status"] not in {"queued", "running"}:
            return None
        task.update({"status": "cancelled", "updatedAt": datetime.now(timezone.utc)})
        return task

    def expired_results(self, now):
        return [task for task in self.tasks.values() if task["status"] == "completed" and task.get("result", {}).get("expiresAt") <= now]

    def expire(self, task_id, result=None):
        task = self.tasks.get(task_id)
        if task and task["status"] == "completed":
            task.update({"status": "expired", "updatedAt": datetime.now(timezone.utc)})
        return task


class Oms3ShiftsReportTest(unittest.TestCase):
    def setUp(self):
        self.main = import_oms3_main()
        self.main.report_task_storage = FakeReportTaskStorage()
        self.published = []
        self.main.publish_event = lambda topic, payload: self.published.append((topic, payload))
        self.main.Thread = ImmediateThread
        self.temp_dir = tempfile.TemporaryDirectory()
        self.main.settings.report_storage_dir = self.temp_dir.name
        self.main.fetch_shifts_from_oms5 = lambda starts_at_from, starts_at_to: [
            {
                "id": "shift-1",
                "client_id": "client-1",
                "starts_at": "2026-10-05T09:00:00Z",
                "ends_at": "2026-10-05T18:00:00Z",
                "status": "A30_CHOICE",
                "location": "Moscow",
                "assigned_performer_id": None,
                "close_reason": None,
                "failure_reason": None,
                "created_at": "2026-10-01T12:00:00Z",
                "updated_at": "2026-10-05T12:00:00Z",
            }
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_creates_completed_shifts_xlsx_report_and_downloads_file(self):
        payload = self.main.ReportTaskCreate(
            reportType="shifts",
            filter={"startsAtFrom": "2026-10-01T00:00:00Z", "startsAtTo": "2026-10-31T23:59:59Z"},
            format="xlsx",
        )

        accepted = self.main.start_report_generation(payload, Response())
        task = self.main.report_task_storage.get(accepted["taskId"])

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"]["expiresAt"].date(), (task["completedAt"] + self.main.timedelta(days=30)).date())
        self.assertEqual(self.published[0][0], "report.requested")
        file_path = Path(task["result"]["filePath"])
        self.assertTrue(file_path.exists())
        with ZipFile(file_path) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("shift_id", sheet)
        self.assertIn("shift-1", sheet)
        self.assertIn("Moscow", sheet)

        response = self.main.download_report(task["id"])

        self.assertEqual(response.media_type, self.main.XLSX_CONTENT_TYPE)
        self.assertEqual(response.filename, task["result"]["fileName"])

    def test_rejects_invalid_shifts_report_period(self):
        payload = self.main.ReportTaskCreate(
            reportType="shifts",
            filter={"startsAtFrom": "2026-10-31T00:00:00Z", "startsAtTo": "2026-10-01T00:00:00Z"},
            format="xlsx",
        )

        with self.assertRaises(self.main.HTTPException) as exc:
            self.main.start_report_generation(payload, Response())

        self.assertEqual(exc.exception.status_code, 422)

    def test_report_task_alias_does_not_emit_pydantic_warning(self):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            payload = self.main.ReportTaskCreate(reportType="shifts", filter={}, format="xlsx")
            self.main.app.openapi()

        self.assertEqual(payload.report_type, "shifts")
        self.assertFalse(any(isinstance(item.message, UnsupportedFieldAttributeWarning) for item in captured))


if __name__ == "__main__":
    unittest.main()
