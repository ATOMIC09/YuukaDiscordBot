FROM python:3.12-slim-bookworm

# Install required system packages
# - ffmpeg: needed for audio/voice features
# - git: needed because pyproject.toml installs py-cord from a git PR branch
# - libgomp1: OpenMP runtime required by CTranslate2 (faster-whisper)
# - intel-media-va-driver-non-free & libva-drm2: needed for Intel QuickSync (QSV) hardware encoding
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libgomp1 \
    intel-media-va-driver-non-free \
    libva-drm2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv from the official astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Environment variables for uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (for docker layer caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application
ADD . /app

# Run the final sync (installs the project itself if applicable)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Ensure the bot runs using the uv environment
CMD ["uv", "run", "main.py"]
