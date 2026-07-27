# Start with a modern, slim, official uv base image
# Pinned to specific digest to prevent upstream updates from invalidating the
# builder's layer cache (which triggers slow QEMU-emulated rebuilds on arm64).
# Update this digest explicitly when upgrading uv.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim@sha256:4f5d923c9dcea037f57bda425dd209f3ec643da2f0b74227f68d09dab0b3bb36

# Set environment variables for Python and define the non-root user
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    APP_USER=app \
    # XDG_CONFIG_HOME ensure we point astropy the astropy configuration to the correct place.
    # https://docs.astropy.org/en/stable/environment_variables.html#environment-variables
    XDG_CONFIG_HOME=/code/.config \
    # Set the path to include the virtual environment's bin directory
    PATH="/code/.venv/bin:$PATH"


# Install system dependencies from the old Dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    poppler-utils \
    tesseract-ocr \
    make \
    netcat-traditional \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libopenblas-dev \
    liblapack-dev \
    libfreetype6-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set working directory and create a non-root user for security
WORKDIR /code
RUN addgroup --gid 1000 $APP_USER && \
    adduser --disabled-password --gecos "" --uid 1000 --gid 1000 $APP_USER

# Install dependencies using uv with advanced caching
# Copy dependency definition files for deterministic builds
COPY pyproject.toml uv.lock ./

# Then, install dependencies. This layer is only rebuilt when pyproject.toml or uv.lock changes.
# The --mount=type=cache command significantly speeds up subsequent builds.
# Using uv.lock ensures Docker gets the same package versions as local development
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv sync --no-dev --frozen --python ./.venv/bin/python

# Remove build tools after Python packages are installed (saves ~300MB)
RUN apt-get purge -y gcc g++ make && apt-get autoremove -y && apt-get clean

# Copy the astropy config file into its location
RUN mkdir -p /code/.config/astropy
COPY astropy.cfg /code/.config/astropy/astropy.cfg
# This is necessary to disable the fast C time parser, which causes seg faults.

# Copy application code with correct ownership (avoids slow recursive chown of .venv)
COPY --chown=app:app api/manage.py /code/
COPY --chown=app:app api/paper_analyzer_app /code/paper_analyzer_app
COPY --chown=app:app api/vso_query_builder /code/vso_query_builder
COPY --chown=app:app ./paper_data_linking /code/paper_data_linking

# Make the entrypoint script executable
COPY --chown=app:app init.sh /usr/src/app/init.sh
RUN chmod +x /usr/src/app/init.sh

# Create runtime directories owned by app (only dirs that need write access)
# .config is XDG_CONFIG_HOME — sunpy, astropy, etc. write config/cache here at runtime
RUN mkdir -p /code/staticfiles /code/media && \
    chown -R $APP_USER:$APP_USER /code/staticfiles /code/media /code/.config

# Create and set a home directory for the non-root user
RUN mkdir -p /home/$APP_USER && chown $APP_USER:$APP_USER /home/$APP_USER
ENV HOME=/home/$APP_USER

## Switch to the non-root user
USER $APP_USER

# Set the PYTHONPATH so your application can be found
ENV PYTHONPATH="/code/"

CMD ["gunicorn", "paper_analyzer_app.wsgi:application", "--bind", "0.0.0.0:8000"]