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
when you apply a ticker edit or select another interval. In pricing, **Price option** sends one
request; **Spot sensitivity** sends nine sequential requests and stops on the first
failure, preserving completed results. In regime, **Load price history** fetches
Yahoo data, and **Analyze regime** sends one API request. Each API action may
consume your allowance. Changing a widget never submits a MorphIQ request.

API keys remain in the kernel environment; shut down the kernel when finished.
An environment-provided key remains in the container configuration until
`docker compose down`; use `unset MORPHIQ_API_KEY` to clear it from your terminal.
Never put keys into saved notebook source, outputs or widget values.

## Configuration and networking

```sh
MORPHIQ_NOTEBOOK_PORT=8889 docker compose up --build
```

The displayed URL uses this host port; the container always listens on 8888.
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
workspace controls against loopback contract fixtures, using synthetic in-memory
prices without contacting Yahoo. It then recreates the container
with the same volume to verify preserved edits and missing-notebook seeding. It removes only its
own randomly named test container and volume.

The image uses a digest-pinned multi-platform Python base and hashed dependency
locks. Registry publishing, release tags, image scanning/provenance and published
image acceptance remain [#14](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/14).
The multi-user hosted website remains [#11](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/11).
