# Bank Ledger

An accounting engine and persistent journal of entries balanced by currency, with idempotency, file locking, integer precision, and hash-chain verification.

## Run

Requirements: Java 17 and Maven.

```sh
mvn test
mvn compile
java -cp target/classes io.brunnodev.ledger.Journal ledger.log post entrada_1 caixa receita BRL 1250
java -cp target/classes io.brunnodev.ledger.Journal ledger.log report > result.json
```

## Behavior

`Journal` records local entries and verifies balances by currency. `BankPlatform` contains transfer, account, and event rules. External banking integrations require their own contracts and credentials; this project does not move funds held by external institutions.

## Result synchronization

The [operations archive](https://vercel-home-telemetry-api.vercel.app/laboratory.html?project=bank-crypto-ledger) stores execution results. Supabase migrations are in the [API repository](https://github.com/brunnojob/vercel-home-telemetry-api/tree/main/supabase/migrations).

```sh
python cloud/sync.py enqueue result.json --project bank-crypto-ledger
python cloud/sync.py sync
```

Set `BRUNNODEV_ACCESS_TOKEN` to your session token. The SQLite outbox retains reports until the server confirms persistence; identical content does not create duplicate records. Tokens are not stored in source code. To run the synchronization tests:

```sh
python -m unittest discover -s cloud
```
