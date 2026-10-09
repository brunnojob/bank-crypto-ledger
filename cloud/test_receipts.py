import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from sync import Outbox


class ReceiptTests(unittest.TestCase):
    def test_invalid_receipts_keep_the_report_pending(self):
        receipts = [[], None, True, 1, "persisted", {}, {"persisted": 1}, {"persisted": False}]
        for receipt in receipts:
            with self.subTest(receipt=receipt), tempfile.TemporaryDirectory() as directory:
                box = Outbox(Path(directory) / "outbox.db")
                try:
                    box.enqueue("test", "report", {"value": 10})
                    response = MagicMock()
                    response.status = 200
                    response.read.return_value = json.dumps(receipt).encode()
                    response.__enter__.return_value = response
                    with patch("sync.urllib.request.build_opener") as opener:
                        opener.return_value.open.return_value = response
                        result = box.drain("https://example.com/api", "token")
                    self.assertEqual(result, {"sent": 0, "failed": 1, "pending": 1})
                    attempts, next_at = box.db.execute("SELECT attempts, next_at FROM outbox").fetchone()
                    self.assertEqual(attempts, 1)
                    self.assertGreater(next_at, 0)
                finally:
                    box.close()

    def test_confirmed_receipt_marks_the_report_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            box = Outbox(Path(directory) / "outbox.db")
            try:
                box.enqueue("test", "report", {"value": 10})
                response = MagicMock()
                response.status = 201
                response.read.return_value = b'{"persisted": true}'
                response.__enter__.return_value = response
                with patch("sync.urllib.request.build_opener") as opener:
                    opener.return_value.open.return_value = response
                    self.assertEqual(
                        box.drain("https://example.com/api", "token"),
                        {"sent": 1, "failed": 0, "pending": 0},
                    )
            finally:
                box.close()

    def test_events_reject_empty_values_of_the_wrong_type(self):
        with tempfile.TemporaryDirectory() as directory:
            box = Outbox(Path(directory) / "outbox.db")
            try:
                for events in ({}, "", 0, False):
                    with self.subTest(events=events), self.assertRaises(ValueError):
                        box.enqueue("test", "report", {"value": 10}, events=events)
                self.assertEqual(box.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 0)
            finally:
                box.close()

    def test_omitted_events_and_empty_list_have_the_same_key(self):
        with tempfile.TemporaryDirectory() as directory:
            box = Outbox(Path(directory) / "outbox.db")
            try:
                self.assertEqual(
                    box.enqueue("test", "report", {"value": 10}),
                    box.enqueue("test", "report", {"value": 10}, events=[]),
                )
            finally:
                box.close()


if __name__ == "__main__":
    unittest.main()
