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
# `requests` is used by tools/qa_ops.py but not declared in pyproject — add it here.
RUN pip install --no-cache-dir . requests

# 9090 = engine WebSocket (TUI/cockpit clients); 9091 = inbound hub dispatch.
EXPOSE 9090 9091

CMD ["python", "-m", "archie_engine"]
