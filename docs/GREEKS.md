# Option price and Greeks

See [model capabilities](MODELS.md) for supported operations,
100-item batch limits and unavailable-Greek semantics.

`client.options.greeks()` (sync and async) calls `options.greeks`,
`POST /v1/options:greeks`. One request returns the option price and all ten
Greeks at the supplied volatility. To start from a market premium instead, use
[implied Greeks](IMPLIED_GREEKS.md). The SDK
does not calculate derivatives, choose the numerical model, or rescale values.

Set `MORPHIQ_API_KEY`, then run a self-contained example:

```sh
python -m examples.greeks
python -m examples.greeks_async
```

Each command sends one request. The examples use synthetic option inputs and
print the price, every Greek, resolved model, engine provenance, request ID and
reported commercial CU. Missing CU is shown as unreported, not zero.

## Python usage

```python
from morphiq_sdk import Market, MorphIQ, Option, OptionsGreeksRequest

request = OptionsGreeksRequest(
    option=Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0),
    market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
    volatility=0.20,
)
with MorphIQ() as client:
    response = client.options.greeks(request)
print(response.result.price)
print(response.result.greeks.delta)
print(response.model_dump_json(indent=2, exclude_unset=True))
```

The asynchronous equivalent uses `async with AsyncMorphIQ()` and
`await client.options.greeks(request)`. `OptionsGreeksRequest` has the same
`option`, `market`, `volatility` and `model` fields and wire serialization rules
as `OptionsPriceRequest`. Rates and volatility are decimals, time is in years, and
spot/strike share the caller's currency. European/American style and the model
selection are forwarded to the service. The service owns dividend-schedule
support and model/domain validation. `result.model` reports the resolved model
id and version.

## Units

These are the bases in the pinned API contract; the SDK preserves them unchanged.
`V` is option value per share, `S` is underlying price, `σ` is decimal volatility,
`r` is the decimal rate, and `t` is time in years.

| Field | Derivative | Basis |
| --- | --- | --- |
| `delta` | dV/dS | Per unit underlying price |
| `gamma` | d²V/dS² | Per underlying price squared |
| `theta` | dV/dt | Per year |
| `vega` | dV/dσ | Per unit volatility |
| `rho` | dV/dr | Per unit rate |
| `vanna` | d²V/(dS dσ) | Per underlying price and unit volatility |
| `volga` | d²V/dσ² | Per unit volatility squared |
| `charm` | d²V/(dS dt) | Per underlying price and year |
| `veta` | d²V/(dσ dt) | Per unit volatility and year |
| `color` | d³V/(dS² dt) | Per underlying price squared and year |

No calendar convention, percentage-point conversion, or option contract multiplier
is applied by the SDK. A Greek the model cannot provide is omitted and explained
in `greeks.unavailable` as a problem with a `code` and `detail`; a Greek that is
neither present nor explained, null or non-finite produces a `ResponseError`.
Values are never replaced with zero. Unknown additive response
fields are preserved, and `raw_body` retains the response evidence with reflected
credentials redacted.

## Pricing workspace

Open [Option pricing](../notebooks/pricing/options.ipynb), initialize its controls,
and select the exercise style, model, call/put and assumptions. **Price + Greeks**
submits one request using those controls and displays a labeled ten-row table,
option price, input snapshot, model, engine identity, request ID and CU evidence.
Changing controls makes no MorphIQ request and does not relabel an existing result.
The notebook's volatility/rate percentage inputs are converted to decimals before
submission. Its controls use continuous dividend yield, without a cash schedule.

Service errors preserve their code, status and charge evidence. A timeout or
malformed response can leave execution and charges unknown. Neither client nor
example retries automatically.

See the [client/model reference](API.md) for shared configuration and errors,
and the [documentation index](README.md) for related features.

## Standard five

`OptionsStandardGreeksRequest` and `client.options.standard_greeks(request)`
return price, delta, gamma, theta, vega and rho from
`POST /v1/options:standard-greeks` (`options.standard_greeks`). The request fields
match `OptionsGreeksRequest`; `max_cu` is supported. Use
`OptionsBatchStandardGreeksRequest` with `client.options.batch_standard_greeks()`
for a single batch, or explicitly chunk with
`client.options.standard_greeks_workflow(..., chunk_size=100)`. Both clients
expose these methods; async client calls use `await` and do not create server jobs.

Run `python examples/standard_greeks.py` or open
`notebooks/pricing/standard-five.ipynb` for an explicit single-request analysis.
