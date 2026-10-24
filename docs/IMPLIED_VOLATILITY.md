# Implied volatility

`MorphIQ.implied_volatility()` and `AsyncMorphIQ.implied_volatility()` call
`POST /v1/implied-volatility`. Supply the option terms and a market premium per
share. The service solves volatility; the SDK preserves the result and diagnostics.

Set `MORPHIQ_API_KEY`, then run either self-contained example:

```sh
python -m examples.implied_volatility
python -m examples.implied_volatility_async
```

Each command sends one request using synthetic option inputs and a synthetic
premium. Neither example downloads data or computes IV locally.

## Python usage

```python
from morphiq_sdk import ImpliedVolatilityRequest, MorphIQ

request = ImpliedVolatilityRequest(
    exercise_style="european",
    option_type="call",
    spot=100.0,
    strike=100.0,
    time_to_expiry_years=1.0,
    risk_free_rate=0.05,
    dividend_yield=0.0,
    market_price=10.450583572185538,
    pricing_model="auto",
)
with MorphIQ() as client:
    response = client.implied_volatility(request)
print(response.result.implied_volatility)
print(response.result.residual, response.result.residual_basis)
print(response.model_dump_json(indent=2, exclude_unset=True))
```

Use `async with AsyncMorphIQ()` and `await client.implied_volatility(request)` for
async execution. `market_price` replaces the pricing request's `volatility` field;
passing `volatility` is an error. Premium, spot and strike use the same currency
and no contract multiplier. Rates and dividend yield are decimals, time is in
years. The service owns model selection, premium bounds and schedule support.
Optional model version and cash-dividend schedule retain their omission/null/empty
semantics; the SDK does not adjust inputs or prices.

## Interpreting the result

| Field | Meaning |
| --- | --- |
| `implied_volatility` | Decimal volatility: 0.2 is 20%. |
| `iterations` | Solver iteration count as reported by the service. |
| `used_fallback` | Algorithm provenance, not a solution-quality flag. American bisection reports true for live solves. |
| `residual` | Solver error in the units named by `residual_basis`. |
| `residual_basis` | `forward_normalised_price` or `option_price`; values on different bases are not directly comparable. |
| `pricing_model`, `model_version` | Resolved model and version used for the solve. |

The pinned native European fixture solves to `0.20000000000000007`, with 2
iterations, `used_fallback=false` and residual `1.3877787807814457e-17` on the
`forward_normalised_price` basis. Its American counterpart uses the `option_price`
basis. Full native results and provenance are retained in
[the fixture](../tests/fixtures/implied_volatility.json).

Required malformed or non-finite result fields produce `ResponseError`; none are
replaced with zero. Unknown additive fields, resolved model names and residual
basis names are retained without interpretation. `raw_body`, headers, engine
identity, request ID and optional commercial CU remain available. Absent
`fcu_charged` means unreported, not zero; `units_charged` is a separate internal
compute weight. Service errors preserve charge evidence. Timeouts or malformed
responses can leave execution and charges unknown; no automatic retries occur.

## Pricing workspace

In [Option pricing](../notebooks/pricing/options.ipynb), choose the exercise style,
model and option terms, then enter **Option premium** and press **Solve IV**. One
request returns IV, iterations, fallback usage and the residual with its basis,
alongside the input snapshot, model, engine identity, request ID and charge.

The premium is entered manually; Yahoo supplies only the underlying price.
Solving does not read or change the pricing volatility assumption. Editing inputs
makes no MorphIQ request and does not relabel a saved result.
