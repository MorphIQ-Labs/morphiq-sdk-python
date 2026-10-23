# Local notebook environment

From a checkout with Docker running:

```sh
docker compose up --build
```

Open the local token-authenticated URL printed by Jupyter to reach Start Here.
The Jupyter access token is separate from the MorphIQ API key entered at the masked
notebook prompt. Compose does not copy a host API key into container configuration.

The container runs as UID 1000, publishes only to localhost, and retains Jupyter's
random token authentication. Dependencies and the SDK wheel are installed during
the build. Startup installs nothing and executes no pricing cells.

The sync cells each make one request; the async cell makes two more. Run All makes
four real requests that may consume your allowance. The API key stays in the kernel
environment until cleanup/kernel shutdown. Never put keys into saved source or outputs.

## Configuration and networking

```sh
MORPHIQ_NOTEBOOK_PORT=8889 docker compose up --build
```

The displayed URL uses this host port; the container always listens on 8888.
Set `MORPHIQ_API_BASE_URL` before startup or enter it in the notebook. Use your
verified HTTPS endpoint for protected calls.

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
only missing notebooks and never replaces an existing edited file.

To adopt a new Start Here after rebuilding, rename your edited copy in Jupyter,
then restart; the missing original filename is seeded from the image. Download
notebooks through Jupyter's file browser for backup or standalone use.
`docker compose down --volumes` deletes the workspace; use it only for an
intentional reset after saving your work.

For startup problems check Docker and host-port availability. For API failures
check the endpoint/network path and typed error. Changing keys needs no rebuild;
changing dependencies or SDK versions does. This first image includes the pricing
notebook dependencies; later plotting/DataFrame recipes can add their own dependencies.

## Source and verification

`scripts/generate_notebook.py` generates Start Here from the executable scripts;
`--check` detects drift. The standalone notebook needs an installed SDK and Jupyter,
but not the repository's examples directory.

```sh
docker compose build
python scripts/check_notebook_container.py
```

This check verifies authenticated startup and non-root execution, runs the sync
and async cells against loopback native-response fixtures, then recreates the
container with the same volume to verify preserved edits. It removes only its
own randomly named test container and volume.

The image uses a digest-pinned multi-platform Python base and hashed dependency
locks. Registry publishing, release tags, image scanning/provenance and published
image acceptance remain [#14](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/14).
The multi-user hosted website remains [#11](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/11).
