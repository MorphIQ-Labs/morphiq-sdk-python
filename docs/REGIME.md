# Regime identification

Get an API key from [the developer portal](https://developers.morphiqlabs.com),
then run from a checkout:

```sh
python -m pip install -e '.[market-data]'
export MORPHIQ_API_KEY="YOUR_API_KEY"
python -m examples.download_prices
python -m examples.identify_regime
```

The download prompts for a Yahoo ticker, defaulting to `SPY`. It requests daily
history ending before today, selects the latest 512 closes, saves `prices.csv`
in the working directory, and displays the latest rows. Change the ticker at
the prompt and rerun the download to replace that file. It stops if there are
fewer than 512 observations or missing/nonpositive values; it does not fill gaps.

`yfinance` is an optional market-data dependency. The download uses `Close` with
`auto_adjust=False` for split-adjusted prices without cash-dividend total-return
adjustment. See [yfinance's adjustment documentation](https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html).
It uses daily date labels, which do not establish an exact observation timestamp,
so the regime request omits `as_of`. An exact known final observation timestamp
can be supplied as RFC 3339 with an explicit UTC offset.

The [sync example](../examples/identify_regime.py) reads the CSV, constructs a
`RegimeRequest(prices=prices)` and calls `MorphIQ.regime`. The
[async example](../examples/identify_regime_async.py) shows the same data and
response handling with `await AsyncMorphIQ.regime`. Both connect to
`https://api.morphiqlabs.com` and read `MORPHIQ_API_KEY`, or prompt for it masked.
The [notebook](../notebooks/regime/identification.ipynb) contains the download,
ticker input and complete sync request code. Docker includes yfinance; outside
Docker install `.[notebooks]` to use it in Jupyter.

## Request and result semantics

Prices must be finite, positive, comparable, and ordered oldest to newest.
Send prices, not returns. At least 512 observations are required. V1 selects
the latest 512 and consumes the latest 507 of that window. All supplied prices
are validated before cropping. No sampling interval is supplied or assumed.
Requests have a 32 KiB encoded body limit that service policy may narrow.

Each of `response.result.decision`, `.direction` and `.state` has a status:

- `available`: read `prediction.label` and each labeled entry in `prediction.scores`.
- `not_applicable`: `prediction` is null; read `reason_code`.
- `unavailable`: `prediction` is null; read `reason_code`.

`unresolved` is an available decision label, not a serving failure. `NEUTRAL`
is a valid direction label. `LOWER_VOL` and `HIGHER_VOL` are relative to the
reference model's other state, not historical volatility norms or directions.
Scores are uncalibrated softmax values, not calibrated probabilities, p-values
or confidence intervals. Treat heads separately; never multiply their scores.
The basis describes the prediction target, not a claim that reference fitting
ran for the request. Read `metadata.provenance.teacher_executed` as reported.

`metadata.consumed_price_range` is a half-open range in the original input
array. `input_price_index` identifies the original price at the selected return's
end. `metadata.provenance` identifies the served model; `metadata.engines`
identifies the inference library. The SDK preserves both and the raw response.

Keep `metadata.request_id` for support. Commercial charges are
`metadata.fcu_charged`; absent means unreported, not zero. Service failures raise
`APIError` with server evidence. Transport failures and malformed responses can
leave execution and charges unknown. Neither client retries automatically.
