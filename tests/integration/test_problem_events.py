import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def import_service_module(service: str, module: str):
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    sys.path.insert(0, str(ROOT / service))
    try:
        return importlib.import_module(module)
    finally:
        sys.path.pop(0)


def base_event(event_id: str = "event-1", **extra):
    event = {
        "event_id": event_id,
        "event_type": "operations.shift.status_changed",
        "schema_version": 1,
        "occurred_at": "2026-10-05T12:00:00Z",
        "correlation_id": "corr-1",
        "producer": "OMS5",
        "shift_id": "shift-1",
        "previous_status": "A20_SOURCING",
        "new_status": "A30_CHOICE",
        "reason": "performer_assigned",
    }
    event.update(extra)
    return event


class ProblemEventsTest(unittest.TestCase):
    def setUp(self):
        self.problem_events = import_service_module("OMS3", "app.problem_events")
        self.main = import_service_module("OMS3", "app.main")
        self.problem_events.problem_events.clear()
        self.problem_events.problem_events_by_event_id.clear()
        self.main.processed_shift_status_events.clear()
        self.main.report_cache_stale_by_shift.clear()
        self.published_retry = []
        self.published_manual = []
        self.problem_events.publish_retry = lambda item: self.published_retry.append((item["id"], item["last_retry_interval"]))
        self.problem_events.publish_manual_reprocess = lambda problem_event_id: self.published_manual.append(problem_event_id)
        self.main.register_problem_event = self.problem_events.register_problem_event

    def test_technical_error_uses_three_retry_intervals_then_manual_review(self):
        event = base_event(reason="force_technical_error")

        for _ in range(4):
            self.main.handle_shift_status_changed(event)

        item = next(iter(self.problem_events.problem_events.values()))
        self.assertEqual(item["attempt_count"], 4)
        self.assertEqual(item["status"], "manual_review")
        self.assertIsNone(item["next_retry_at"])
        self.assertEqual(self.published_retry, [(item["id"], "5m"), (item["id"], "15m"), (item["id"], "1h")])

    def test_business_error_goes_to_pending_without_retry(self):
        self.main.handle_shift_status_changed(base_event(external_store_id="missing"))

        item = next(iter(self.problem_events.problem_events.values()))
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["error_code"], "store_not_found")
        self.assertEqual(self.published_retry, [])

    def test_contract_error_goes_to_dlq(self):
        self.main.handle_shift_status_changed(base_event(schema_version=2))

        item = next(iter(self.problem_events.problem_events.values()))
        self.assertEqual(item["status"], "dlq")
        self.assertEqual(item["error_code"], "unsupported_schema_version")

    def test_manual_reprocess_sends_only_problem_event_id(self):
        self.main.handle_shift_status_changed(base_event(external_store_id="missing"))
        item = next(iter(self.problem_events.problem_events.values()))

        self.problem_events.enqueue_manual_reprocess(item["id"], "operations", "fixed")

        self.assertEqual(self.published_manual, [item["id"]])
        self.assertEqual(item["status"], "retry_scheduled")
        self.assertEqual(item["last_manual_comment"], "fixed")

    def test_reprocess_is_idempotent_after_resolved(self):
        self.main.handle_shift_status_changed(base_event(external_store_id="missing"))
        item = next(iter(self.problem_events.problem_events.values()))
        item["payload"].pop("external_store_id")

        self.problem_events.reprocess_problem_event(item["id"], self.main.process_shift_status_changed_event)
        self.problem_events.reprocess_problem_event(item["id"], self.main.process_shift_status_changed_event)

        self.assertEqual(item["status"], "resolved")
        self.assertEqual(len(self.main.processed_shift_status_events), 1)

    def test_later_shift_event_waits_for_earlier_unresolved_event(self):
        first = base_event("event-1", external_store_id="missing")
        second = base_event("event-2")
        self.problem_events.register_problem_event(
            first,
            self.problem_events.EventProcessingError("business", "store_not_found", "Store is not registered in platform"),
            "OMS3",
            {"source_topic": "operations.shift.status_changed", "source_partition": 0, "source_offset": 1, "kafka_key": "shift-1"},
        )
        second_item = self.problem_events.register_problem_event(
            second,
            self.problem_events.EventProcessingError("technical", "temporary_dependency_error", "Temporary dependency error"),
            "OMS3",
            {"source_topic": "operations.shift.status_changed", "source_partition": 0, "source_offset": 2, "kafka_key": "shift-1"},
        )

        self.problem_events.reprocess_problem_event(second_item["id"], self.main.process_shift_status_changed_event)

        self.assertEqual(second_item["status"], "pending")
        self.assertEqual(second_item["error_code"], "earlier_shift_event_unresolved")


class Oms4ProblemEventsSmokeTest(unittest.TestCase):
    def test_oms4_business_error_registers_pending(self):
        problem_events = import_service_module("OMS4", "app.problem_events")
        main = import_service_module("OMS4", "app.main")
        problem_events.problem_events.clear()
        problem_events.problem_events_by_event_id.clear()
        problem_events.publish_retry = lambda item: None
        main.register_problem_event = problem_events.register_problem_event

        main.handle_shift_status_changed(base_event(external_store_id="missing"))

        item = next(iter(problem_events.problem_events.values()))
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["consumer_service"], "OMS4")


if __name__ == "__main__":
    unittest.main()
