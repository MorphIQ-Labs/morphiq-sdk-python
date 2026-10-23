FROM python:3.14-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae AS builder
WORKDIR /build
COPY requirements-build.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.txt
COPY pyproject.toml README.md ./
COPY src ./src
ARG MORPHIQ_SDK_BUILD_VERSION=0.0.0.dev0
RUN MORPHIQ_SDK_BUILD_VERSION=${MORPHIQ_SDK_BUILD_VERSION} python -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir /wheels .

FROM python:3.14-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements-notebook.txt /tmp/requirements-notebook.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements-notebook.txt \
    && rm /tmp/requirements-notebook.txt
COPY --from=builder /wheels /tmp/wheels
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels \
    && useradd --create-home --uid 1000 notebook \
    && mkdir -p /home/notebook/work \
    && chown notebook:notebook /home/notebook/work
COPY notebooks/00-start-here.ipynb /opt/morphiq/notebooks/00-start-here.ipynb
COPY docker/start_notebook.py /opt/morphiq/start_notebook.py
USER notebook
WORKDIR /home/notebook/work
EXPOSE 8888
HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/login', timeout=2)"
ENTRYPOINT ["python", "/opt/morphiq/start_notebook.py"]
