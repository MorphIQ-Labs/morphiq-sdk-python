# Price European and American options

This guide covers `options.price` (`POST /v1/options:price`) over JSON,
synchronously and asynchronously. See [all SDK features](README.md) for Greeks,
IV, implied Greeks, batches and regime.
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
python3 -m venv .venv
source .venv/bin/activate
python -m pip install morphiq-sdk
```

## 3. Make your first API request

Save this as `price_option.py`. `MorphIQ()` reads `MORPHIQ_API_KEY` automatically:

```python
from morphiq_sdk import Market, MorphIQ, Option, OptionsPriceRequest

request = OptionsPriceRequest(
    option=Option(type="call", exercise_style="european", strike=100.0, time_to_expiry_years=1.0),
    market=Market(spot=100.0, risk_free_rate=0.05, dividend_yield=0.0),
    volatility=0.20,
)

with MorphIQ() as client:
    response = client.options.price(request)
    print(response.model_dump_json(indent=2, exclude_unset=True))
```

Run it in the terminal where you exported your key:

```sh
python price_option.py
```

This sends one authenticated `POST https://api.morphiqlabs.com/v1/options:price`
request and prints the JSON response.

See the [example JSON response](../README.md#3-make-your-first-api-request) for
the recorded price, model identity and metadata.

## Run the repository examples

The `examples` scripts and Docker notebooks are provided in the repository.
To use them, clone it and install the checked-out SDK in your active environment:

```sh
git clone https://github.com/MorphIQ-Labs/morphiq-sdk-python.git
cd morphiq-sdk-python
python -m pip install -e .
python -m examples.quickstart
```

The quickstart script sends two requests, pricing one European call and one
American put. The executable examples also support a masked key prompt when
`MORPHIQ_API_KEY` is unset. See [the cookbook](../examples/README.md) for all scripts.

## Inputs and results

A request has three parts: `Option` holds the contract terms (`type`,
`exercise_style`, `strike`, `time_to_expiry_years`), `Market` holds the
underlying's market (`spot`, `risk_free_rate`, `dividend_yield` and optional cash
`dividends`), and `model` holds a `ModelSelection`. Forward operations take
`volatility`; inverse operations take the premium as `market_price` instead.

Monetary inputs use the same currency. Rates, continuous yield and volatility are
decimal fractions: 0.05 means 5%, 0.01 means 1%, and 0.20 means 20%. Expiry is in
years. This example does no calendar/day-count conversion, and no contract
multiplier is applied to the returned price.

`model` defaults to `ModelSelection(id="auto")` and is sent explicitly. The server
selects the model; inspect the returned `result.model.id` and
`result.model.version`. The SDK rejects malformed types and
non-finite numbers, while model-domain validation and numerical calculations stay
on the server. It never clamps inputs or substitutes a pricing algorithm.

The American put uses spot 100, strike 105, expiry 0.5 years, rate 0.05,
continuous dividend yield 0.01 and volatility 0.20. It is a different contract
from the European call, so the difference is not an early-exercise-premium
comparison. Typed `DividendEvent` inputs in `Market.dividends` support
cash-dividend schedules, but those are outside this introductory example.

`Market.dividends` remains an editable list even though request attributes are
frozen. Appended events are validated and included when either client sends the
request. Invalid edits raise a Pydantic `ValidationError` before any HTTP request.
An empty schedule is omitted from the request body.

Run each script separately with `python -m examples.price_european` or
`python -m examples.price_american`.

Each script shows its request inputs, response fields and error handling in full.
They also run directly as `python examples/price_european.py` and
`python examples/price_american.py`, with no repository helper imports.

The [native reference fixtures](../tests/fixtures/pricing.json) record about
**10.450583572185577** for the European call (`black_scholes_merton/1`) and
**7.5298454349124135** for the American put (`bjerksund_stensland_1993/1`). These
results belong to the recorded service/engine identity; they are not universal
expectations for future models selected by `auto`. Request IDs vary. The fixture
service ran in open mode and omitted commercial charges.

## Async usage

```python
import asyncio
from morphiq_sdk import AsyncMorphIQ


async def price_option():
    async with AsyncMorphIQ() as client:
        response = await client.options.price(request)
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
an explicit argument takes precedence. Use the API root without an operation path.
The default timeout is 30 seconds per connect/read/write/pool wait, not an overall
end-to-end deadline. Pass `httpx.Timeout` to configure them separately. Proxy and
CA environment variables are not used automatically; an HTTPX transport can supply
advanced network configuration.

Wrap an existing call with this pattern when you need application error handling:

```python
from morphiq_sdk import (
    APIError,
    MorphIQ,
    RateLimitError,
    RequestTimeout,
    ResponseError,
    TransportError,
)

try:
    with MorphIQ() as client:
        response = client.options.price(request)
except RateLimitError as error:
    print("Rate limited:", error.code, error.request_id)
    print("Retry-After:", error.retry_after, "Delay in seconds:", error.retry_delay())
    charged = error.metadata.charged_cu if error.metadata else None
    print("Commercial CU charge:", charged if charged is not None else "unreported")
    # Decide when to submit a new request; this handler does not retry.
except APIError as error:
    print(error.status_code, error.code, error.detail, error.field, error.request_id)
    charged = error.metadata.charged_cu if error.metadata else None
    print("Commercial CU charge:", charged if charged is not None else "unreported")
except ResponseError as error:
    print("Invalid response:", error.request_id)
    charged = error.metadata.charged_cu if error.metadata else None
    print("Commercial CU charge:", charged if charged is not None else "unreported")
except RequestTimeout:
    print("No complete response; execution and charges may be unknown.")
except TransportError:
    print("Transport failure; check the endpoint before resubmitting.")
```

API failures are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problems.
`APIError` exposes `code`, `title`, `detail`, `field` (a public request path such
as `market.spot`), optional `solve_trial`, the shared `metadata` and the whole
typed `problem`, plus headers, `retry_after` and the response body. Non-JSON
gateway failures remain inspectable with those problem attributes left `None`.
Malformed success bodies raise `ResponseError`, retaining independently valid
response metadata when available. A 429 raises `RateLimitError` even for a non-JSON gateway
body. See [429 handling](BATCH.md#http-429) for retry guidance and charge semantics.
Use request IDs for support, not keys.

Neither client automatically retries requests or follows redirects. A server can
commit work before a client timeout; another submission can incur another charge.
`error.metadata.charged_cu` is shorthand for `metadata.billing.charged_cu`; a
missing value means unreported, not zero. `metadata.budget.remaining_estimate_cu`
is an estimate, not an authoritative balance.

Responses preserve additive fields through `model_dump(exclude_unset=True)`.
The API omits absent members rather than sending null. Response enums may gain
values; the SDK keeps an unknown value as a string instead of failing.
`response.raw_body` and `response.headers` allow explicit response inspection
without retaining the credential-bearing HTTP request.

## Notebook and controlled local service

From the repository checkout, use `docker compose up --build`, or install the
notebook extra and open the included notebooks:

```sh
python -m pip install -e '.[notebooks]'
jupyter lab notebooks/start-here.ipynb
```

The [notebook guide](NOTEBOOKS.md) covers credentials, analysis controls,
workspace persistence and networking. Start Here links to the pricing and regime
workspaces. Run All initializes their controls without MorphIQ requests; actions
send requests only when pressed. The workspaces are self-contained and do not
import the repository's examples module.

For a controlled open local service only, set a non-secret placeholder such as
`MORPHIQ_API_KEY=local-development-only` when running scripts, or use
`allow_unauthenticated=True` with no key when constructing a client. This does not
authenticate against a protected service. Configure the local endpoint explicitly;
the SDK does not start that service.

See [the rate card and request quotes](RATE_CARD.md) for zero-CU discovery, conditional quotes, and the optional `max_cu` execution ceiling.
