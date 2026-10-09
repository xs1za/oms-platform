import importlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[3]


def import_oms5_main():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    sys.path.insert(0, str(ROOT / "OMS5"))
    try:
        return importlib.import_module("app.main")
    finally:
        sys.path.pop(0)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def shift_item(shift_id: str, starts_at: str) -> dict:
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    return {
        "id": shift_id,
        "client_id": "client-1",
        "starts_at": dt(starts_at),
        "ends_at": dt(starts_at).replace(hour=18),
        "status": "A30_CHOICE",
        "location": "Moscow",
        "assigned_performer_id": None,
        "close_reason": None,
        "failure_reason": None,
        "created_at": now,
        "updated_at": now,
        "auto_closed": False,
        "auto_close_reason": None,
    }


class Oms5InternalShiftsTest(unittest.TestCase):
    def setUp(self):
        self.main = import_oms5_main()
        self.main.shifts.clear()

    def test_lists_only_shifts_inside_period_sorted_by_starts_at_then_id(self):
        self.main.shifts.update(
            {
                "outside-before": shift_item("outside-before", "2026-09-30T09:00:00Z"),
                "inside-b": shift_item("inside-b", "2026-10-05T09:00:00Z"),
                "inside-a": shift_item("inside-a", "2026-10-05T09:00:00Z"),
                "outside-after": shift_item("outside-after", "2026-11-01T09:00:00Z"),
            }
        )

        result = self.main.list_internal_shifts(
            starts_at_from=dt("2026-10-01T00:00:00Z"),
            starts_at_to=dt("2026-10-31T23:59:59Z"),
        )

        payload = [self.main.InternalShiftRead(**item).model_dump(mode="json") for item in result]
        self.assertEqual([item["id"] for item in payload], ["inside-a", "inside-b"])
        self.assertEqual(payload[0]["starts_at"], "2026-10-05T09:00:00Z")
        self.assertNotIn("auto_closed", payload[0])

    def test_rejects_invalid_period_and_too_large_period(self):
        with self.assertRaises(HTTPException) as invalid_period:
            self.main.list_internal_shifts(dt("2026-10-31T00:00:00Z"), dt("2026-10-01T00:00:00Z"))
        with self.assertRaises(HTTPException) as too_large:
            self.main.list_internal_shifts(dt("2026-01-01T00:00:00Z"), dt("2027-01-02T00:00:01Z"))

        self.assertEqual(invalid_period.exception.status_code, 422)
        self.assertEqual(too_large.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
