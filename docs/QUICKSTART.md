# Price European and American options

This preview supports `POST /v1/price` over JSON, synchronously and asynchronously.
You need Python 3.11+ and an API key. The SDK connects to
`https://api.morphiqlabs.com` by default. The examples use synthetic contracts
and no market data.

## 1. Get API access

Start at the [MorphIQ Labs developer portal](https://developers.morphiqlabs.com)
to get your API key, then set it in your terminal:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
```

## 2. Install the SDK

```sh
git clone https://github.com/MorphIQ-Labs/morphiq-sdk-python.git
cd morphiq-sdk-python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The repository is currently private and requires access. This development build
has not been released; `pip install morphiq-sdk` is not yet a supported path.

## 3. Make your first API request

This sends one authenticated `POST https://api.morphiqlabs.com/v1/price` request
using the key you exported, then prints the JSON response:

```python
from morphiq_sdk import MorphIQ, PriceRequest

request = PriceRequest(
    exercise_style="european",
    option_type="call",
    spot=100.0,
    strike=100.0,
    time_to_expiry_years=1.0,
    risk_free_rate=0.05,
    dividend_yield=0.0,
    volatility=0.20,
)

with MorphIQ() as client:
    response = client.price(request)
    print(response.model_dump_json(indent=2, exclude_unset=True))
```

See the [example JSON response](../README.md#3-make-your-first-api-request) for
the recorded price, model identity and metadata. Run `unset MORPHIQ_API_KEY` when
finished. The executable examples also support a masked key prompt when the
environment variable is unset.

## Inputs and results

Monetary inputs use the same currency. Rates, continuous yield and volatility are
decimal fractions: 0.05 means 5%, 0.01 means 1%, and 0.20 means 20%. Expiry is in
years. This example does no calendar/day-count conversion, and no contract
multiplier is applied to the returned price.

`pricing_model` defaults to `"auto"` and is sent explicitly. The server selects
the model; inspect the returned identity. The SDK rejects malformed types and
non-finite numbers, while model-domain validation and numerical calculations stay
on the server. It never clamps inputs or substitutes a pricing algorithm.

The American put uses spot 100, strike 105, expiry 0.5 years, rate 0.05,
continuous dividend yield 0.01 and volatility 0.20. It is a different contract
from the European call, so the difference is not an early-exercise-premium
comparison. Typed `DividendEvent` inputs support cash-dividend schedules, but
those are outside this introductory example.

The dividend schedule remains an editable list even though request attributes are
frozen. Appended events are validated and included when either client sends the
request. Invalid edits raise a Pydantic `ValidationError` before any HTTP request.
An untouched, omitted schedule stays omitted; an explicitly supplied empty list
is sent as `[]`.

Run each script separately with `python -m examples.price_european` or
`python -m examples.price_american`.

Each script shows its request inputs, response fields and error handling in full.
They also run directly as `python examples/price_european.py` and
`python examples/price_american.py`, with no repository helper imports.

The [native reference fixtures](../tests/fixtures/pricing.json) record about
**10.450583572185538** for the European call (`black_scholes_merton/1`) and
**7.584143004464017** for the American put (`bjerksund_stensland_2002/1`). These
results belong to the recorded service/engine identity; they are not universal
expectations for future models selected by `auto`. Request IDs vary. The fixture
service ran in open mode and omitted commercial charges.

## Async usage

```python
import asyncio
from morphiq_sdk import AsyncMorphIQ


async def price_option():
    async with AsyncMorphIQ() as client:
        response = await client.price(request)
        print(response.result.price, response.metadata.request_id)


asyncio.run(price_option())  # In a script; use await price_option() in Jupyter.
```

This uses the same `request` defined above. The runnable
`python -m examples.price_async` script prices both options with sequential awaits,
so it works with a one-request concurrency allowance. Async does not imply parallel
submission. Close pools using the context managers, or `close()`/`await aclose()`.

## Configuration and errors

Both clients accept explicit `base_url`, `api_key`, and `timeout` arguments.
The default API URL is `https://api.morphiqlabs.com`. For a local or controlled
test service, override it with `MORPHIQ_API_BASE_URL` or the `base_url` argument;
an explicit argument takes precedence. Use the API root without `/v1/price`.
The default timeout is 30 seconds per connect/read/write/pool wait, not an overall
end-to-end deadline. Pass `httpx.Timeout` to configure them separately. Proxy and
CA environment variables are not used automatically; an HTTPX transport can supply
advanced network configuration.

Wrap an existing call with this pattern when you need application error handling:

```python
from morphiq_sdk import APIError, RequestTimeout, TransportError

try:
    response = client.price(request)  # Inside the client's context manager.
except APIError as error:
    print(error.status_code, error.code, error.request_id)
    charged = error.metadata.fcu_charged if error.metadata else None
    print("Commercial CU charge:", charged if charged is not None else "unreported")
except RequestTimeout:
    print("No complete response; execution and charges may be unknown.")
except TransportError:
    print("Transport failure; check the endpoint before resubmitting.")
```

`APIError` also retains headers, `retry_after`, response body, server message and
optional typed metadata. Non-JSON gateway failures remain inspectable. Malformed
success bodies raise `ResponseError`. Use request IDs for support, not keys.

Neither client automatically retries requests or follows redirects. A server can
commit work before a client timeout; another submission can incur another charge.
Missing `fcu_charged` means unreported, not zero. `units_charged` is an internal
compute weight, and `remaining_fcu_instance_estimate` is not an authoritative balance.

Responses preserve additive fields through `model_dump(exclude_unset=True)`.
`response.raw_body` and `response.headers` allow explicit response inspection
without retaining the credential-bearing HTTP request.

## Notebook and controlled local service

Use `docker compose up --build`, or install the notebook extra:

```sh
python -m pip install -e '.[notebooks]'
jupyter lab notebooks/quickstart/start-here.ipynb
```

The [notebook guide](NOTEBOOKS.md) covers credentials, four-call Run All behavior,
workspace persistence and networking. The generated notebook uses the same tested
example functions and runs without the repository's examples module.

For a controlled open local service only, set a non-secret placeholder such as
`MORPHIQ_API_KEY=local-development-only` when running scripts, or use
`allow_unauthenticated=True` with no key when constructing a client. This does not
authenticate against a protected service. Configure the local endpoint explicitly;
the SDK does not start that service.
