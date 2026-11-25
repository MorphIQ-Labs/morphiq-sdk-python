# Executable cookbook

Get your API key from the
[MorphIQ Labs developer portal](https://developers.morphiqlabs.com). After
[installing the SDK](../docs/QUICKSTART.md), clone the repository to get these
scripts and run them from its root:

```sh
git clone https://github.com/MorphIQ-Labs/morphiq-sdk-python.git
cd morphiq-sdk-python
python -m pip install -e .
export MORPHIQ_API_KEY="YOUR_API_KEY"
python examples/quickstart.py
```

The other examples use the same environment settings:

```sh
python examples/price_european.py
python examples/price_american.py
python examples/price_async.py
python examples/greeks.py
python examples/greeks_async.py
python examples/implied_volatility.py
python examples/implied_volatility_async.py
python examples/standard_greeks.py
python examples/implied_greeks.py
python examples/implied_greeks_async.py
python examples/batch_price.py
python examples/batch_price_async.py
```

Each connects to `https://api.morphiqlabs.com` and reads `MORPHIQ_API_KEY`, or
prompts for the key with masked input. Set `MORPHIQ_API_BASE_URL` only to use a
local or controlled test service.
Run `unset MORPHIQ_API_KEY` when finished.
Each option example is self-contained: it constructs the appropriate typed request,
calls the SDK and reads the operation-specific result, model identity, request/engine
provenance and reported commercial CU charges. The error handlers show API failure
details and distinguish unknown charges after transport failures. Scripts exit
with a nonzero status on request-level failure and do not retry. An accepted
batch can contain per-item errors, which its example prints alongside successes.

The quickstart uses one sync client for two explicit option requests; the async
script awaits them sequentially. Imports make no requests. You can copy a script
outside this repository and run it with the SDK installed.

See [the quickstart](../docs/QUICKSTART.md) and [all feature guides](../docs/README.md).
Start Here links to the interactive workspaces; the standalone scripts remain the
SDK usage demonstrations.

Every request is built from the same parts: an `Option` (type, exercise style,
strike, time to expiry), a `Market` (spot, rates, optional cash dividends), a
`volatility` or a `market_price`, and a `ModelSelection`. Methods are grouped by
the API's collections and spell its canonical operation ids: `client.options.price()`
is `options.price` (`POST /v1/options:price`). Results report the resolved
`model.id` and its exact `model.version`; a charge is read from
`metadata.billing.charged_cu`.

The Greeks examples submit `OptionsGreeksRequest` to `client.options.greeks()` and
display the price plus all ten derivatives, with the same model/charge evidence and error
handling. Values use annual time units and unit volatility/rate bases. The
standard-Greeks example calls `client.options.standard_greeks()` for the price and
delta, gamma, theta, vega and rho. See [the Greeks guide](../docs/GREEKS.md).

The implied-volatility examples pass an explicit option premium to
`client.options.implied_volatility()` and print IV, residual with its basis, iterations,
fallback usage and provenance. See [the IV guide](../docs/IMPLIED_VOLATILITY.md).

The implied-Greeks examples submit one `OptionsImpliedGreeksRequest` to
`client.options.implied_greeks()` to solve IV from a premium and evaluate price and
all ten Greeks at that solved volatility. They report the combined response's
commercial charge once. See [implied Greeks](../docs/IMPLIED_GREEKS.md).

The batch examples submit two explicit pricing requests as `items` in one
`client.options.batch_price()` call, preserve ordered item outcomes, and count the
response charge once. See
[batch operations and 429 handling](../docs/BATCH.md).

The [chunked pricing examples](../docs/WORKFLOWS.md) prepare five synthetic spot
scenarios and send three sequential batch requests. They retain partial results
and exact reported CU subtotals if a request fails, without retries:

```sh
python examples/chunked_price.py
python examples/chunked_price_async.py
python examples/chunked_price_async.py --max-concurrency 2
```

The async example defaults to sequential execution. The optional flag bounds
simultaneous requests; it does not change chunk size or retry failed requests.

## Regime and optional price data

These examples download Yahoo history; they require the optional data extra:

```sh
python -m pip install -e '.[market-data]'
export MORPHIQ_API_KEY="YOUR_API_KEY"
python examples/identify_regime.py
python examples/identify_regime_async.py
python examples/provider_regime.py
```

Each script submits one `client.series.identify_regime()` request. The first two prompt for a ticker and
support a masked key prompt; the provider example uses SPY and requires the
exported key. See [regime interpretation](../docs/REGIME.md) and
[provider interfaces](../docs/PRICE_PROVIDERS.md). Data stays in memory; no CSV
intermediate is required. The provider example lets errors propagate; it does not
retry. These scripts do not make Yahoo a core SDK dependency.

## Optional tabular analysis

The [tabular pricing example](tabular_price.py) sends five synthetic spot scenarios
in three sequential requests and displays separate result and charge tables:

```sh
python -m pip install -e '.[pandas]'
export MORPHIQ_API_KEY="YOUR_API_KEY"
python examples/tabular_price.py
```

See [the pandas adapter guide](../docs/PANDAS.md) for partial results, identifiers,
units and exact charge totals. Pandas is optional and conversion makes no API calls.

## Model catalog and rate card

```sh
python examples/list_models.py
python examples/rate_card_quote.py
python examples/rate_card_quote.py --batch --execute
```

`list_models.py` calls the public `client.models.list()` without a key or charge
and prints each model's canonical operation ids and validity contracts.
`rate_card_quote.py` reads your rate card with `client.rate_card.get()` and quotes
the exact request it would execute with `client.rate_card.quote()`; both are
utility requests. `--execute` then sends one pricing request with the quoted
total as its `max_cu` ceiling. See [the rate card guide](../docs/RATE_CARD.md).

## Option scenarios and books

Each script uses synthetic inputs and sends one calculation when run. All request
construction and the complete returned result are visible; missing charges stay
unreported. Set `MORPHIQ_API_KEY`, then run:

```sh
python examples/option_revalue.py
python examples/option_solve.py
python examples/book_revalue.py
python examples/book_explain.py
python examples/book_solve.py
```

[The guide](../docs/SCENARIOS.md) explains targets, units, coverage, signed values
and quotation. The [local solver app](solver_app/README.md) separates Quote and
Solve into explicit actions with a single-use quote and retained receipts.
