# Bank Crypto Ledger

An educational transaction ledger demonstrating AES-GCM payload encryption, signed records, idempotency and tamper-evident audit chaining.

## Run

```bash
python -m pip install .
python ledger.py
```

Set `LEDGER_KEY` to a 32-byte hex key before use. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.

This is a local simulation, not a banking system or payment processor. Never use test keys for real financial data.
