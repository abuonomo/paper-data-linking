# The standalone batch runner: vLLM plus the paper pipeline, no database.
# Build from the repository root:  docker build -f runner/Dockerfile -t pdl-runner .
#
# The base is the vLLM release the L40S recipe was measured on. For a GPU-free image
# (dry runs against the built-in fake server, or `pdl-batch run` against vLLM running
# elsewhere) build with:  --build-arg BASE_IMAGE=python:3.11-slim
ARG BASE_IMAGE=vllm/vllm-openai:v0.32.0
FROM ghcr.io/astral-sh/uv:0.7.8 AS uv
FROM ${BASE_IMAGE}

COPY --from=uv /uv /usr/local/bin/uv

# The runner gets its own interpreter and virtualenv under /opt/pdl so that none of
# its dependencies can change what vLLM imports.
ENV UV_PROJECT_ENVIRONMENT=/opt/pdl/.venv \
    UV_PYTHON_INSTALL_DIR=/opt/pdl/python \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/pdl

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --only-group runner --frozen --no-install-project --python 3.11

COPY paper_data_linking ./paper_data_linking
COPY runner/pdl-batch /usr/local/bin/pdl-batch
# The .pth file puts /opt/pdl on the runner interpreter's path without a PYTHONPATH
# that the vLLM processes it starts would inherit.
RUN chmod +x /usr/local/bin/pdl-batch && mkdir -p /data/papers /data/out && \
    echo /opt/pdl > "$(/opt/pdl/.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')/pdl.pth"

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} \
    PDL_PAPERS=/data/papers \
    PDL_OUT=/data/out \
    HF_HUB_OFFLINE=1

ENTRYPOINT ["pdl-batch"]
CMD ["all"]
