# Spot solver example app

A local browser app for `client.options.solve_scenario` on API 0.10.0, with BSM
and BS1993, option-price and signed position-P&L targets. Quote calls
`client.rate_card.quote`; Solve sends one capped request. Neither action retries.

```sh
python -m pip install -e .
export MORPHIQ_API_KEY="YOUR_API_KEY"
python examples/solver_app/app.py
```

Open the printed loopback URL. `--port 0` selects a free port. Credentials stay
in the Python process; origin checks restrict actions to that loopback page.
This is a single-user example; tabs share one current quote.

Enter synthetic option inputs, target and spot bounds, then Quote and Solve.
Percent controls become decimal API inputs. Changing inputs invalidates the
quote and current result; earlier receipts remain. The quote is consumed before
execution, including a timeout, so a second click cannot repeat a charge.

Results show point/interval boundaries, regions, unresolved cells and full raw
response receipts. Intervals describe sampled evidence; unresolved coverage is
not proof of no solution. Position P&L uses the base model value, not trade entry.
Only `metadata.billing.charged_cu` is a charge; a quote and price-evaluation count
are not charges. Missing, zero and large integer receipts remain distinct.

See [scenario and book semantics](../../docs/SCENARIOS.md). The standalone
notebooks cover all solve coordinates and book operations through editable inputs.
