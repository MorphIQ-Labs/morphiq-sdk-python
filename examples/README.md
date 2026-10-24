# Executable cookbook

Get your API key from the
[MorphIQ Labs developer portal](https://developers.morphiqlabs.com). After
[installing the SDK](../docs/QUICKSTART.md), replace the placeholders and run:

```sh
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
```

Each connects to `https://api.morphiqlabs.com` and reads `MORPHIQ_API_KEY`, or
prompts for the key with masked input. Set `MORPHIQ_API_BASE_URL` only to use a
local or controlled test service.
Run `unset MORPHIQ_API_KEY` when finished.
Each file is self-contained: it constructs `PriceRequest` with the option inputs,
calls the SDK, reads the price and model identity, and prints request/engine
provenance and reported commercial CU charges. The error handlers show API failure
details and distinguish unknown charges after transport failures. Scripts exit
with a nonzero status on failure and do not retry.

The quickstart uses one sync client for two explicit option requests; the async
script awaits them sequentially. Imports make no requests. You can copy a script
outside this repository and run it with the SDK installed.

See [the quickstart](../docs/QUICKSTART.md). Start Here includes the complete code
from these tested scripts.

The Greeks examples submit `GreeksRequest` to `client.greeks()` and display the
price plus all ten derivatives, with the same model/charge evidence and error
handling. Values use annual time units and unit volatility/rate bases. See
[the Greeks guide](../docs/GREEKS.md).
