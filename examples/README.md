# Executable cookbook

Eight recipes are planned in [#7](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/7).
The first pricing slice is runnable now:

```sh
python -m examples.quickstart
python -m examples.price_european
python -m examples.price_american
python -m examples.price_async
```

Each reads the endpoint/key from the environment or prompts (masked for the key).
Imports make no requests. `_shared.py` supplies synthetic inputs and result display.
The quickstart configures once and uses one sync client for both options; the
async script awaits them sequentially. See [the quickstart](../docs/QUICKSTART.md).
Start Here is generated from these tested sources. The broader recipes below are
planned beyond this initial pricing slice.

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
