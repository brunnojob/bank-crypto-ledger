import tempfile
import unittest
from pathlib import Path
from sync import Outbox


class OutboxTests(unittest.TestCase):
    def test_retries_keep_reports_until_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            box = Outbox(Path(directory) / "outbox.db")
            key = box.enqueue("c-household-budget", "report", {"minor": 10})
            self.assertEqual(
                key, box.enqueue("c-household-budget", "report", {"minor": 10})
            )
            self.assertEqual(
                box.drain(
                    "https://example.com/api", "token", transport=lambda *args: 503
                )["pending"],
                1,
            )
            box.db.execute("UPDATE outbox SET next_at=0")
            box.db.commit()
            self.assertEqual(
                box.drain(
                    "https://example.com/api", "token", transport=lambda *args: 200
                )["pending"],
                0,
            )
            box.close()

    def test_conflicting_key_cannot_overwrite_a_report(self):
        with tempfile.TemporaryDirectory() as directory:
            box = Outbox(Path(directory) / "outbox.db")
            box.enqueue("test", "report", {"a": 1}, key="fixed")
            with self.assertRaises(ValueError):
                box.enqueue("test", "report", {"a": 2}, key="fixed")
            box.close()
