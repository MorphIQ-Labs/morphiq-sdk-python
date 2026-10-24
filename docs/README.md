# SDK documentation

Start with [API access, installation and your first request](QUICKSTART.md).
The [client and model reference](API.md) lists every supported method, its inputs,
response types, configuration and errors.

| Task | Guide | Executable examples |
| --- | --- | --- |
| Price European/American options | [Pricing quickstart](QUICKSTART.md) | [European](../examples/price_european.py), [American](../examples/price_american.py), [async](../examples/price_async.py) |
| Calculate price and ten Greeks | [Greeks and units](GREEKS.md) | [Sync](../examples/greeks.py), [async](../examples/greeks_async.py) |
| Solve volatility from an option premium | [Implied volatility](IMPLIED_VOLATILITY.md) | [Sync](../examples/implied_volatility.py), [async](../examples/implied_volatility_async.py) |
| Solve IV and evaluate price/Greeks together | [Combined analytics and CU accounting](ANALYTICS.md) | [Sync](../examples/analytics.py), [async](../examples/analytics_async.py) |
| Submit ordered batches | [Batches, per-item failures and 429s](BATCH.md) | [Sync pricing batch](../examples/batch_price.py), [async pricing batch](../examples/batch_price_async.py) |
| Run explicit chunks with optional async concurrency | [Batch workflows and exact costs](WORKFLOWS.md) | [Sync](../examples/chunked_price.py), [async](../examples/chunked_price_async.py) |
| Analyze batches as pandas tables | [Optional DataFrame adapter](PANDAS.md) | [Tabular pricing](../examples/tabular_price.py) |
| Identify the latest market regime | [Regime inputs and interpretation](REGIME.md) | [Sync](../examples/identify_regime.py), [async](../examples/identify_regime_async.py) |
| Supply data through an optional provider | [Provider interface and Yahoo adapter](PRICE_PROVIDERS.md) | [Provider to regime](../examples/provider_regime.py) |
| Use the interactive analysis workspaces | [Notebook controls, Docker and persistence](NOTEBOOKS.md) | [Workspace index](../notebooks/README.md) |

All numerical methods have sync and async equivalents. Option examples use
synthetic terms; the regime/provider examples download Yahoo data using the
optional `market-data` extra. Core SDK calls accept caller-supplied data and have
no Yahoo or pandas dependency.

For development, see [contributing](../CONTRIBUTING.md),
[contract ownership and provenance](CONTRACT.md) and [release procedures](../RELEASE.md).
