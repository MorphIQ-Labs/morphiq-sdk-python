# Local notebook environment

Get your API key from the
[MorphIQ Labs developer portal](https://developers.morphiqlabs.com). From a checkout
with Docker running, replace the key placeholder and start the notebook:

```sh
export MORPHIQ_API_KEY="YOUR_API_KEY"
docker compose up --build
```

Open the local token-authenticated URL printed by Jupyter to reach Start Here.
Choose [option pricing](../notebooks/pricing/options.ipynb) or
[regime analysis](../notebooks/regime/identification.ipynb), then select
**Run → Run All Cells** to initialize the controls. The start page and both
workspaces are included in the image.
Compose passes the key into the container at runtime; it is not baked into the
image. The notebook connects to `https://api.morphiqlabs.com` automatically. Leave
the key unset to enter it at the masked notebook prompt instead. The Jupyter
access token in the local URL is separate from your MorphIQ API key.

The container runs as UID 1000, publishes only to localhost, and retains Jupyter's
random token authentication. Dependencies and the SDK wheel are installed during
the build. Startup installs nothing and executes no API calls.

Running setup makes no MorphIQ requests. Pricing fetches Yahoo data on setup and
when you apply a ticker edit or select another interval. Choose daily, 1-minute,
5-minute, 15-minute, 30-minute or hourly prices. Regime fetches a longer history
to obtain 512 prices. Its **Analyze regime** button downloads and validates history,
then submits the request and displays results in one click. If Yahoo returns too few
valid prices, no MorphIQ request is sent. No separate data-loading cell is required.
Choose the action that matches the analysis you need:

| Action | Inputs and result | MorphIQ requests |
| --- | --- | --- |
| **Price option** | Supplied volatility and option terms → price and comparison history | 1 |
| **Price + Greeks** | Supplied volatility and option terms → price and all ten Greeks | 1 |
| **Solve IV** | Entered per-share option premium and terms → IV and solver diagnostics | 1 |
| **Analyze premium** | Entered premium and terms → native combined IV, price and Greeks at solved IV | 1 |
| **Spot sensitivity** | Nine spots across ±20%, other assumptions fixed → ordered outcomes and chart | 1 batch of 9 items |
| **Analyze regime** | Ticker/interval → Yahoo history, latest regime assessment and score charts | 1 on a fresh analysis |

The regime workspace can redraw its saved response with **Show analysis** without
another request. Changing the selected data invalidates that cached result.
In pricing, pressing an API action again submits a new request. Input changes
and Yahoo downloads alone never submit MorphIQ requests.

Yahoo supplies the underlying price, not an option premium. Enter **Option premium**
manually. The pricing widgets take volatility, rate and dividend yield as percentages
(20 means 20%); the SDK receives decimals. Expiry is in years, monetary values are
per share, and no contract multiplier is applied. IV actions do not replace the
volatility assumption used by the other pricing controls. Cash-dividend schedules
can be supplied through SDK requests but are outside these notebook controls.
See [Greek units](GREEKS.md#units), [IV diagnostics](IMPLIED_VOLATILITY.md#interpreting-the-result)
and [regime interpretation](REGIME.md#request-and-result-semantics).

**Session CU** sums only reported `fcu_charged` values, once per request. Combined
results and batches count once, not per returned component or item. Charged failures
are included; missing charges, transport failures and user interruptions leave an
explicitly incomplete subtotal. Rerunning setup retains the ledger in that kernel;
restarting the kernel resets it. It covers the pricing workspace, not account-wide
usage. Failed batch items remain rows and chart gaps. A 429 displays the server's
`Retry-After`; no automatic retry or batch splitting occurs. See
[batch errors and throttling](BATCH.md).

API keys remain in the kernel environment; shut down the kernel when finished.
An environment-provided key remains in the container configuration until
`docker compose down`; use `unset MORPHIQ_API_KEY` to clear it from your terminal.
Never put keys into saved notebook source, outputs or widget values.

## Configuration and networking

```sh
MORPHIQ_NOTEBOOK_PORT=8889 docker compose up --build
```

The displayed URL uses this host port; the container always listens on 8888.
Compose also accepts a local `.env` file containing `MORPHIQ_API_KEY=...`.
It is ignored by Git and excluded from the image build context. Shell exports
take precedence over `.env`. The plain Python SDK does not load that file;
export the key for scripts or a locally launched Jupyter process.
After changing `.env` or exported configuration, use `docker compose up -d`
to recreate the container as needed; `docker compose start` alone reuses the old
environment. The key stays in the container environment until it is removed.

The API URL needs no configuration. For a local or controlled test service,
set `MORPHIQ_API_BASE_URL` before startup to override the default.

For an API on the Docker host, use `http://host.docker.internal:PORT` inside the
notebook. Container localhost refers to the container itself. Docker Desktop
supports this hostname; Compose also adds the host-gateway alias on Linux. On
Linux the API must listen on an interface reachable from the gateway: a service
bound only to host 127.0.0.1 is not reachable that way. Keep open development
services confined to a controlled local network. For another container use its
service name on a shared Docker network.

## Preserve and refresh your work

The `notebook-work` named volume stores notebooks and outputs. Ctrl-C followed
by `docker compose down` retains it; subsequent startup reuses it. Startup seeds
only missing notebooks and never replaces an existing edited file. Rebuilding and
restarting adds new feature notebooks to an existing workspace.
The quickstart is `start-here.ipynb` at the workspace root. Feature notebooks are
organized by feature, with option pricing in `pricing/`
and regime identification in `regime/`.

To adopt an updated notebook after rebuilding, rename your edited copy in Jupyter,
then restart; the missing original filename is seeded from the image. Download
notebooks through Jupyter's file browser for backup or standalone use.
`docker compose down --volumes` deletes the workspace; use it only for an
intentional reset after saving your work.

For startup problems check Docker and host-port availability. For API failures
check the endpoint/network path and typed error. After changing an exported key,
rerun `docker compose up -d` to recreate the container with the new setting. Keys
entered at the notebook prompt can be changed by restarting the kernel. Changing keys needs no rebuild;
changing dependencies or SDK versions does. The image includes Jupyter, ipywidgets, matplotlib and yfinance for the
pricing and regime workspaces.

## Source and verification

`scripts/generate_notebook.py` generates the start page and verifies that analysis
notebooks have no saved outputs or widget state. Workspaces are authored directly
as self-contained notebooks; their actions are verified against the reviewed
contract and executable examples. They need the SDK and notebook extra installed,
but do not import repository helpers.

```sh
docker compose build
python scripts/check_notebook_container.py
```

This check verifies authenticated startup and non-root execution, runs every
workspace's controls against loopback contract fixtures, using synthetic in-memory
prices without contacting Yahoo. It then recreates the container
with the same volume to verify preserved edits and missing-notebook seeding. It removes only its
own randomly named test container and volume.

The image uses a digest-pinned multi-platform Python base and hashed dependency
locks. Registry publishing, release tags, image scanning/provenance and published
image acceptance remain [#14](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/14).
The multi-user hosted website remains [#11](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/11).
