# Regime identification

Get an API key from [the developer portal](https://developers.morphiqlabs.com),
then run from a checkout:

```sh
python -m pip install -e '.[market-data]'
export MORPHIQ_API_KEY="YOUR_API_KEY"
python -m examples.identify_regime
```

The example prompts for a Yahoo ticker, defaulting to `SPY`. It requests daily
history ending before today, selects the latest 512 closes in memory, and displays
the latest rows. It passes those prices directly to the regime request. It stops if there are
fewer than 512 observations or missing/nonpositive values; it does not fill gaps.

`yfinance` is an optional market-data dependency. The download uses `Close` with
`auto_adjust=False` for split-adjusted prices without cash-dividend total-return
adjustment. See [yfinance's adjustment documentation](https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html).
It uses daily date labels, which do not establish an exact observation timestamp,
so the regime request omits `as_of`. An exact known final observation timestamp
can be supplied as RFC 3339 with an explicit UTC offset.

The [sync example](../examples/identify_regime.py) constructs
`SeriesIdentifyRegimeRequest(prices=closes["Close"].tolist())` and calls
`client.series.identify_regime` (`series.identify_regime`,
`POST /v1/series:identify-regime`). The
[async example](../examples/identify_regime_async.py) shows the same data and
response handling with `await client.series.identify_regime`. Both connect to
`https://api.morphiqlabs.com` and read `MORPHIQ_API_KEY`, or prompt for it masked.
The [analysis workspace](../notebooks/regime/identification.ipynb) provides ticker
selection, a price-history chart, an Analyze button, head results and score charts. Docker includes yfinance; outside
Docker install `.[notebooks]` to use it in Jupyter.

## Request and result semantics

Prices must be finite, positive, comparable, and ordered oldest to newest.
Send prices, not returns. At least 512 observations are required. V1 selects
the latest 512 and consumes the latest 507 of that window. All supplied prices
are validated before cropping. No sampling interval is supplied or assumed.
Requests have a 32 KiB encoded body limit that service policy may narrow.

Each of `response.result.decision`, `.direction` and `.state` has a status:

- `available`: read `prediction.label` and each labeled entry in `prediction.scores`.
- `not_applicable`: `prediction` is omitted; read `reason_code`.
- `unavailable`: `prediction` is omitted; read `reason_code`.

The SDK types these as `RegimeAvailable`, `RegimeNotApplicable` and
`RegimeUnavailable`; a status this SDK version does not know is kept as
`Unrecognized` with all its wire members. Labels are lower snake case.
`unresolved` is an available decision label, not a serving failure. `neutral`
is a valid direction label (with `up` and `down`). `lower_vol` and `higher_vol`
are relative to the reference model's other state, not historical volatility
norms or directions. A label this SDK version does not list is kept as a string.
Scores are uncalibrated softmax values, not calibrated probabilities, p-values
or confidence intervals. Treat heads separately; never multiply their scores.
The basis describes the prediction target, not a claim that reference fitting
ran for the request. Read `result.provenance.teacher_executed` as reported.

Regime facts are part of the result. `result.input` holds the window and return
facts: `received_price_count`, `window_price_count`, `price_count`,
`return_count`, `consumed_price_range` (a half-open range in the original input
array), `observation_index`, `input_price_index` (the original price at the
selected return's end), `all_prices_consumed`, `return_type`, `return_unit` and
`as_of` when the request supplied it. `result.timing` reports `inference_us` and
`crisis_us` in microseconds. `result.provenance` identifies the served model and
`result.response_contract_version` the regime response contract;
`metadata.engines` identifies the inference library. The SDK preserves all of
them and the raw response.

Regime responses carry the same `metadata` as every other operation. Keep
`metadata.request_id` for support. Commercial charges are
`metadata.billing.charged_cu`; absent means unreported, not zero. Service failures raise
`APIError` with server evidence. Transport failures and malformed responses can
leave execution and charges unknown. Neither client retries automatically.

See the [client/model reference](API.md) for shared configuration and errors,
and the [documentation index](README.md) for related features.

## Crisis and the served volatility label

`result.volatility` reports the served volatility label: read its status before
`prediction.label`, which is `low`, `high` or `crisis`. This rule-selected label
has no scores. A crisis detector episode takes precedence; otherwise the label
uses the student's relative state. It is not a forecast or historical norm.

`result.crisis.status` is `crisis`, `not_crisis` or `unavailable`. An active
episode (`RegimeCrisisActive`) includes `score` and `episode_start_price_index`
in the original input array. `not_crisis` (`RegimeNotCrisis`) has a `score` and
omits the episode index. An `unavailable` result (`RegimeCrisisUnavailable`)
omits both and carries a `short_reference` or `degenerate_reference` reason; it
never means not-crisis. The detector is an
acute-shock signal whose short episodes can recur, not a persistent regime.

`result.crisis_score_contract` defines the linear readout and entry/exit
thresholds. The score is unbounded, can be negative, and is not a probability,
confidence or softmax value. Do not apply the other heads' score contract to it.
`result.provenance.crisis` and `.volatility_label` identify both components and
the combination rule. `result.timing.crisis_us` measures detector work separately
from student inference (`result.timing.inference_us`). See the [API regime guide](https://developers.morphiqlabs.com/docs/regime)
for applicability and expected signal rates.
