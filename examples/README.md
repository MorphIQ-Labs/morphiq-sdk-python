# Executable cookbook

Eight recipes are planned in [#111](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/111).
No runnable API examples exist in this scaffold yet.

| Recipe | Outcome |
| --- | --- |
| First price | Authenticate, price one option, inspect request/charge metadata |
| Exercise styles and dividends | Supported European/American inputs and model selection |
| Option-chain analytics | Batch IV, Greeks and fused analytics with item failures |
| CSV and DataFrames | Load synthetic data, enrich it and export results |
| Portfolio Greeks | Positions, contract multipliers and explicit Greek units |
| Scenario grid | Revalue supported contracts over spot/volatility inputs and plot |
| Regime analysis | Required window, applicability and output provenance |
| Reliable async integration | Bounded concurrency, limits, errors and timeouts |

Each recipe must run as a script against a controlled API, with synthetic fixtures
or a deterministic generator, expected output, execution command and optional
dependencies. Explain units, annualization, expiry, dividends, ordering, missing
values and charging where relevant.

Keep endpoint and credentials explicit. Never request on import or commit keys,
private market observations or authenticated notebook outputs. Portfolio and
scenario examples identify local arithmetic and use existing operations; they
must not imply that planned server endpoints exist.

Notebook companions and website snippets derive from or verify against the same
executable source. Pandas and plotting belong in optional extras when implemented.
