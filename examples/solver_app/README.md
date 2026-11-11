# Spot solver example app

A small local browser app that uses the Python SDK to solve for an underlying
spot at a target option price or position P&L. It supports **BSM (European)** and
**BS1993 (American)**, calls `MorphIQ.quote()` and `MorphIQ.solve_spot()`, and
renders the API's boundaries, sign regions, coverage and receipts. There is no
local option-pricing formula, root finder or hidden verification price call.

Requires the compatible scenario API and account permission. This candidate SDK
is held for the matching API deployment; existing published versions may not
contain the solver. See the [scenario contract](../../docs/SCENARIOS.md).

## Run

From this SDK checkout with Python 3.11 or newer:

```sh
python -m pip install -e .
export MORPHIQ_API_KEY="YOUR_API_KEY"
# Set this only for a compatible controlled service; the SDK default is production.
export MORPHIQ_API_BASE_URL="http://127.0.0.1:18080"
python examples/solver_app/app.py
```

Open the printed **http://127.0.0.1:8765** URL. Use `--port 0` to choose a free
port, or `--port 8766` to select another. Stop with Ctrl+C and unset the environment
variables when finished. The app adds no dependencies beyond the SDK and Python's
standard library. You may copy this entire folder outside the checkout and run
it with the matching SDK installed.

The key stays in the Python process. Only the printed loopback origin can submit
actions. This is a single-user development example with one current quote, not a
hosted multiuser service; multiple tabs replace each other's current quote.
Responses/receipts stay in the page session and are cleared on reload.

## Use

1. Enter the base contract, model, target and positive ordered spot bounds.
   Inputs are synthetic by default. Volatility/rates/yield are percentages in
   the form and become decimal fractions in the request; times are years.
2. Click **Get quote**: one free API request, no numerical solve or reservation.
3. Set the maximum CU. The approved flat rate is **100 CU for BSM** or **200 CU
   for BS1993** per complete solve. The authenticated quote is authoritative;
   switching models does not increase your CU limit automatically.
4. Click **Solve**: one capped API request, with all internal pricing included.
   Each execution consumes its quote in the app; another solve needs a new quote.
5. Inspect all boundaries, values/residuals, regions, unresolved cells and the
   complete API response. Receipts retain request IDs, charges and policy/engine
   provenance. Results never imply global completeness beyond the reported scan.

Changing inputs clears the current quote/results and sends no API calls; previous
receipts remain visible. P&L is relative to the original base model mark and uses
signed quantity and a positive contract multiplier. It excludes trade-entry cost,
fees, financing and currency conversion. Strike/rates/yield remain fixed; optional
scenario volatility and elapsed years are shown under assumptions. An interval
represents a sampled plateau, not proof about every spot inside it.

The app refuses below-quote caps before sending a solve; the API independently
enforces the same ceiling. No-root and incomplete searches still carry the full
flat charge. API failures display reported charge evidence. Missing responses or
missing charge metadata mean **unknown**, not zero; there are no automatic retries.
Reconcile an unknown outcome before deliberately submitting again.

## Acceptance walkthrough

Use an explicitly configured controlled API with the pinned contract and approved
solve schedule. Never point automated tests at a billed production account.

| Demonstration | Inputs/action | Expected observation |
| --- | --- | --- |
| Target option price | Defaults: call, spot/strike 100, one year, 20% vol, 5% rate, target 15, range 50–150 | BSM quote/receipt 100 CU; returned point value matches target within reported tolerance |
| American target | Switch to BS1993, quote, keep cap 100 then click Solve | Local refusal without a solve; set cap 200 and explicitly solve for a 200-CU receipt |
| Position P&L | Each model, P&L target 500, quantity 2, multiplier 100 | Base-relative position target and boundaries returned; same model flat rate |
| No boundary in scan | BSM call, target price 1000, range 50–150 | Empty boundaries with actual coverage/sign regions; no claim of global nonexistence; 100 CU |
| Sampled interval | BSM call, elapsed time 1 year, target 0, range 50–90 | Interval boundary at expiry; all returned intervals retained; 100 CU |
| Incomplete search | Defaults, spot tolerance 100, value tolerance 1e-16 | Unresolved cells/reasons remain visible, not presented as a unique solved answer; 100 CU |
| Refusal | Minimum spot greater than maximum spot, then Get quote | Typed API refusal/receipt; no solve automatically submitted |
| Stale result | Edit spot after a successful solve | Current result/quote invalidated; receipt retained; no request from editing |

The app is the **solver slice** of API #34's client acceptance. Point/curve/grid
examples and notebooks remain separate; this app does not complete portfolio
scenarios or attribution. API #146's billing acceptance uses the same app's
quote/cap/receipt flow. Source tests also replay post-commit numerical failure,
zero-charge API refusal, malformed responses and transport disconnects without
retry or invented zero charges.

```sh
python -m pytest -q tests/test_solver_app.py
# Against the controlled protected native candidate only:
MORPHIQ_TEST_API_URL=http://127.0.0.1:18080 \
MORPHIQ_TEST_API_KEY="LOCAL_TEST_KEY" \
python -m pytest -q tests/test_solver_app.py -m integration
```

The native test checks the served OpenAPI digest before executing both models'
price/P&L, no-boundary, interval and unresolved fixtures through the app's HTTP
routes and the installed SDK. Results must exactly match retained native API
fixtures, and quotes/receipts must be 100/200 CU. This verifies adapter parity;
numerical reference accuracy and engine speed remain the API/engine's existing
qualification gates. It is not a production deployment or visual-browser sign-off.
