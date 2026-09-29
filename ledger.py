from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class LedgerRecord:
    sequence: int
    idempotency_key: str
    nonce: str
    ciphertext: str
    previous_hash: str
    record_hash: str


class CryptoLedger:
    def __init__(self, master_key: bytes):
        if len(master_key) < 32:
            raise ValueError("master key must contain at least 32 bytes")
        self._encryption_key = hashlib.sha256(b"ledger-encryption:" + master_key).digest()
        self._signing_key = hashlib.sha256(b"ledger-signing:" + master_key).digest()
        self._records: list[LedgerRecord] = []
        self._requests: dict[str, tuple[str, int]] = {}

    @property
    def records(self) -> tuple[LedgerRecord, ...]:
        return tuple(self._records)

    def submit(self, source: str, destination: str, amount: str, reference: str, idempotency_key: str) -> LedgerRecord:
        value = Decimal(amount)
        if not value.is_finite() or value <= 0 or value.as_tuple().exponent < -2:
            raise ValueError("amount must be positive with at most two decimal places")
        if not source or not destination or source == destination or not reference or not idempotency_key:
            raise ValueError("transfer identifiers are invalid")
        payload = {
            "amount": format(value.quantize(Decimal("0.01")), "f"),
            "currency": "USD",
            "destination": destination,
            "reference": reference,
            "source": source,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        prior = self._requests.get(idempotency_key)
        if prior:
            if not hmac.compare_digest(prior[0], fingerprint):
                raise ValueError("idempotency key reused with a different request")
            return self._records[prior[1]]
        sequence = len(self._records)
        nonce = secrets.token_bytes(12)
        aad = f"ledger:v1:{sequence}:{idempotency_key}".encode()
        ciphertext = AESGCM(self._encryption_key).encrypt(nonce, encoded, aad)
        previous_hash = self._records[-1].record_hash if self._records else "0" * 64
        fields = {
            "ciphertext": ciphertext.hex(),
            "idempotency_key": idempotency_key,
            "nonce": nonce.hex(),
            "previous_hash": previous_hash,
            "sequence": sequence,
        }
        record_hash = hmac.new(self._signing_key, self._canonical(fields), hashlib.sha256).hexdigest()
        record = LedgerRecord(**fields, record_hash=record_hash)
        self._records.append(record)
        self._requests[idempotency_key] = (fingerprint, sequence)
        return record

    def decrypt(self, record: LedgerRecord) -> dict[str, Any]:
        aad = f"ledger:v1:{record.sequence}:{record.idempotency_key}".encode()
        raw = AESGCM(self._encryption_key).decrypt(bytes.fromhex(record.nonce), bytes.fromhex(record.ciphertext), aad)
        return json.loads(raw)

    def verify(self) -> bool:
        previous_hash = "0" * 64
        seen: set[str] = set()
        for index, record in enumerate(self._records):
            if record.sequence != index or record.previous_hash != previous_hash or record.idempotency_key in seen:
                return False
            fields = {
                "ciphertext": record.ciphertext,
                "idempotency_key": record.idempotency_key,
                "nonce": record.nonce,
                "previous_hash": record.previous_hash,
                "sequence": record.sequence,
            }
            expected = hmac.new(self._signing_key, self._canonical(fields), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, record.record_hash):
                return False
            try:
                self.decrypt(record)
            except Exception:
                return False
            previous_hash = record.record_hash
            seen.add(record.idempotency_key)
        return True

    @staticmethod
    def _canonical(value: dict[str, Any]) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def main() -> None:
    raw_key = os.environ.get("LEDGER_KEY")
    if raw_key is None:
        print("Set LEDGER_KEY to a 32-byte hexadecimal secret.")
        return
    try:
        master_key = bytes.fromhex(raw_key)
        ledger = CryptoLedger(master_key)
        ledger.submit("acct-001", "acct-002", "125.50", "invoice-42", "request-42")
        print(json.dumps({"record_count": len(ledger.records), "valid": ledger.verify()}))
    except (ValueError, InvalidOperation) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
