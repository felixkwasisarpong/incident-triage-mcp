FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy only dependency metadata first for caching
COPY pyproject.toml /app/pyproject.toml
# If you have a uv.lock, copy it too (recommended)
# COPY uv.lock /app/uv.lock

# Install deps (and your project) into the container environment
RUN uv sync || true

# Copy the rest of your project
COPY . /app

# Ensure deps are synced after full copy (safe)
RUN uv sync

EXPOSE 3333

# Run MCP server in streamable-http mode on 0.0.0.0:3333
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=3333

CMD ["uv", "run", "python", "-m", "incident_triage_mcp.server"]