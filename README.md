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

## Optional report archive

Export a JSON report from the command above, then run `python cloud/sync.py enqueue result.json --project bank-crypto-ledger` and `python cloud/sync.py sync`. Synchronization requires `BRUNNODEV_ACCESS_TOKEN` and the external operations API; the local outbox retains unacknowledged reports.

## License

Original source and documentation are MIT licensed; see [LICENSE](LICENSE). Third-party dependencies and media retain their respective terms. Maintained by [Brunno Dev](https://brunnodev.store).
