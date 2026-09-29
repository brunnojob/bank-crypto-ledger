# Bank Crypto Ledger

Java transfer engine with double-entry postings, balance reservation, idempotency, an authenticated outbox and AES-GCM data envelopes.

## Run

```bash
mvn test
mvn exec:java
```

The included rail is a deterministic sandbox adapter. The core is built for a real provider integration, but this repository does not move funds or claim a live bank connection. Configure provider credentials only in a private deployment.


# UPDATED VERSION 2.0