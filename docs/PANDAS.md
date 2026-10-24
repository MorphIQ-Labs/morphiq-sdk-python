# Optional pandas tables

Convert accepted batches or sequential workflows into analysis tables without
making API requests, downloading prices or writing files. Install from a checkout:

```sh
python -m pip install -e '.[pandas]'
```

The extra adds pandas only. The core SDK has no pandas or market-data dependency;
even importing `morphiq_sdk.pandas` does not import pandas until conversion.

## Convert results

Import `batch_to_frames`, `workflow_to_frames` and the returned `BatchFrames` type
from `morphiq_sdk.pandas`. All four batch operations are supported: pricing,
Greeks, implied volatility and combined analytics. Responses from sync and async
clients use the same synchronous conversion functions.

For an accepted batch response:

```python
from morphiq_sdk.pandas import batch_to_frames

# response is a BatchPriceResponse, BatchGreeksResponse,
# BatchImpliedVolatilityResponse or BatchAnalyticsResponse from an SDK call.
frames = batch_to_frames(response, identifiers=["contract-A", "contract-B"])
print(frames.results.to_string(index=False))
print(frames.requests.to_string(index=False))
```

Supply one identifier per original input. Identifiers are optional local labels,
never sent to the API. Strings, Python integers and `None` are accepted; duplicates
are preserved. A wrong-length list or other identifier type is rejected. There
is no automatic alignment or joining by identifier.

For a prepared, completed or stopped [workflow](WORKFLOWS.md):

```python
from morphiq_sdk.pandas import workflow_to_frames

# workflow has finished or stopped; identifiers cover every original input,
# including failed and unattempted inputs.
frames = workflow_to_frames(workflow, identifiers=contract_ids)
print(frames.reported_fcu_charged)
print(frames.unknown_charge_count)
print(frames.total_fcu_charged)
```

A running workflow is rejected to avoid presenting a partial moving view.
Conversion never starts or resumes the workflow. A ready workflow produces
unattempted result rows and an empty request table. An empty completed workflow
produces two empty tables and total cost zero.

Run the self-contained synthetic scenario example, which sends three requests:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
python -m examples.tabular_price
```

## Result table

`frames.results` has one row per original input, in input order:

| Column | Meaning |
| --- | --- |
| `index` | Original zero-based input position, across all chunks |
| `identifier` | Caller label, or `None` when labels were omitted |
| `request_index` | Row identifier in the request table; `None` for unattempted inputs |
| `item_index` | Position within that input's chunk; raw response indices stay local |
| `status` | `success`, `error`, `request_error`, `interrupted`, or `unattempted` |
| `outcome` | Full item outcome dictionary with its original local index, or `None` when no validated outcome exists |
| `result.*` | Available typed result fields, such as `result.price` or `result.greeks.delta` |
| `error.*` | Item-level error fields, such as `error.code`, `error.message`, `error.field` |

An accepted numerical item failure has status `error`. A whole-request failure
has status `request_error` for each affected input. Cancellation/interruption
uses `interrupted`. Later unsent inputs remain `unattempted`. Request failure
details live in the request table; they are not invented item-level API errors.

Result columns depend on the available responses. If every request failed there
may be no `result.price` column. Failed rows have missing result values, never
zero-filled prices or Greeks. Use `pd.isna()` for nullable cells.

Floats use pandas nullable `Float64` columns and booleans use `boolean` where
present. Integer columns, including identifiers, iterations and charges, use
`object` to retain arbitrary-precision Python integers with missing values.
This avoids lossy float coercion and fixed-width integer overflow. No numerical
rounding, percentage scaling, annualization or currency conversion occurs; see
[API result units](API.md#response-access).

Full `outcome` dictionaries retain unknown additive fields and distinguish
omitted fields from explicit nulls. Only known typed fields are flattened, so
future names containing dots cannot overwrite a typed column. Flattened missing
cells do not distinguish omission from null; use `outcome` for that distinction.

## Request table and costs

`frames.requests` has exactly one row per attempted HTTP request, including
failed requests. Unattempted chunks have no receipt row.

| Column | Meaning |
| --- | --- |
| `request_index` | Zero-based attempt identifier used by result rows |
| `start`, `stop` | Original input range `[start, stop)` |
| `status` | `completed` (validated response), `request_error`, or `interrupted` |
| `request_id` | Server request ID when known |
| `fcu_charged` | Reported commercial CU as a Python integer, or `None` |
| `metadata` | Full available API metadata, including engine provenance and optional commercial fields |
| `response_extras` | Additive top-level response fields outside `metadata` and `results`, or `None` without a validated response |
| `error` | Request error type, SDK message and available HTTP status/code/field/Retry-After; `None` for completed requests |

Result rows have no charge column. The request table keeps one charge for the
whole chunk even when it has many successes or failures. Do not sum charges
after joining the request table onto result rows: that duplicates receipts.

The `BatchFrames` summary is captured at conversion time:

- `state`: `completed` for an accepted batch, otherwise the workflow's state.
- `reported_fcu_charged`: exact integer subtotal of reported charges.
- `unknown_charge_count`: attempted requests without reported charges.
- `total_fcu_charged`: total only when work completed and every attempted charge
  is known; otherwise `None`.

A reported zero is known. Missing/null charges remain unknown. A normal pandas
sum can skip missing values, so use this summary to distinguish a known subtotal
from a complete total. Quotes and internal `units_charged` do not contribute.

These are independent in-memory snapshots. Editing a table, including a nested
payload, does not modify the original SDK response/workflow or recalculate the
captured summary. Keep original responses for raw body/header evidence. Generic
CSV export does not preserve nested payloads, optional-field semantics or types.

For lossless reconstruction of a batch payload, combine the request row's
`response_extras` with its `metadata` and the result rows' `outcome` dictionaries
in order. For workflows, group by
`request_index` and preserve each outcome's local index. Rows with no validated
outcome cannot be reconstructed as successful API responses.
