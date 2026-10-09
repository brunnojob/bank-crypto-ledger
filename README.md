# Bank Ledger

Motor contábil e diário persistente de partidas balanceadas por moeda, com idempotência, bloqueio de arquivo, precisão inteira e verificação de encadeamento.

## Executar

Requisitos: Java 17 e Maven.

```sh
mvn test
mvn compile
java -cp target/classes io.brunnodev.ledger.Journal ledger.log post entrada_1 caixa receita BRL 1250
java -cp target/classes io.brunnodev.ledger.Journal ledger.log report > resultado.json
```

## Funcionamento

`Journal` registra as partidas locais e confere saldo por moeda. `BankPlatform` contém regras de transferência, contas e eventos. O projeto não movimenta fundos de instituições externas; integrações bancárias precisam de contrato e credenciais próprias.

## Persistência de resultados

O arquivo de operações está em [vercel-home-telemetry-api.vercel.app](https://vercel-home-telemetry-api.vercel.app/laboratory.html?project=bank-crypto-ledger). As migrações Supabase estão no [repositório da API](https://github.com/brunnojob/vercel-home-telemetry-api/tree/main/supabase/migrations).

```sh
python cloud/sync.py enqueue resultado.json --project bank-crypto-ledger
python cloud/sync.py sync
```

Defina `BRUNNODEV_ACCESS_TOKEN` com sua sessão. A fila SQLite conserva os relatórios até confirmação do servidor; o mesmo conteúdo não gera registros duplicados. Tokens não são gravados no código.
