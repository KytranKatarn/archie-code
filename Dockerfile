# ARCHIE Engine — the "building machine" daemon (hub-connected coding brain).
# Runs the WebSocket engine (TUI/cockpit clients) + the hub client.
FROM python:3.12-slim

WORKDIR /app

# git: the engine's GitOpsTool/skill-sync shell out to git.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install deps first (better layer caching), then the package.
COPY pyproject.toml README.md ./
COPY archie_engine ./archie_engine
# `.[dev]` adds pytest + pytest-asyncio so the autonomous build loop's test stage
# (`python -m pytest -q`, #4256) can actually run inside the container (#4258).
# `requests` is used by tools/qa_ops.py but not declared in pyproject — add it here.
RUN pip install --no-cache-dir .[dev] requests

# Entrypoint provisions the writable /workspace as a live archie-code checkout
# and points git config at the writable /data volume before launching the engine
# (#4258 — the read-only rootfs + empty volume otherwise block the build loop).
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 9090 = engine WebSocket (TUI/cockpit clients); 9091 = inbound hub dispatch.
EXPOSE 9090 9091

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "archie_engine"]
