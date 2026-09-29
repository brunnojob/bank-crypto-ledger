import unittest

from ledger import CryptoLedger


class CryptoLedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = CryptoLedger(b"k" * 32)

    def test_encrypted_records_verify_and_decrypt(self):
        record = self.ledger.submit("a", "b", "12.34", "invoice", "req-1")
        self.assertNotIn(b"12.34", bytes.fromhex(record.ciphertext))
        self.assertEqual(self.ledger.decrypt(record)["amount"], "12.34")
        self.assertTrue(self.ledger.verify())

    def test_idempotent_request_returns_same_record(self):
        first = self.ledger.submit("a", "b", "12.34", "invoice", "req-1")
        second = self.ledger.submit("a", "b", "12.34", "invoice", "req-1")
        self.assertEqual(first, second)
        self.assertEqual(len(self.ledger.records), 1)

    def test_reused_key_with_different_payload_is_rejected(self):
        self.ledger.submit("a", "b", "12.34", "invoice", "req-1")
        with self.assertRaises(ValueError):
            self.ledger.submit("a", "b", "99.00", "invoice", "req-1")

    def test_tampering_breaks_verification(self):
        record = self.ledger.submit("a", "b", "12.34", "invoice", "req-1")
        self.ledger._records[0] = type(record)(**{**record.__dict__, "ciphertext": "00"})
        self.assertFalse(self.ledger.verify())


if __name__ == "__main__":
    unittest.main()
