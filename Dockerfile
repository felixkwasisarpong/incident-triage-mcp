FROM python:3.11-slim

ARG VERSION=dev
ARG VCS_REF=unknown

LABEL io.modelcontextprotocol.server.name="io.github.felixkwasisarpong/incident-triage-mcp" \
      org.opencontainers.image.title="incident-triage-mcp" \
      org.opencontainers.image.description="Model Context Protocol server for evidence-driven incident triage with safe actions and workflow integrations." \
      org.opencontainers.image.source="https://github.com/felixkwasisarpong/incident-triage-mcp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy only dependency metadata first for caching
COPY pyproject.toml /app/pyproject.toml

# Install deps (and your project) into the container environment
RUN uv sync || true

# Copy the rest of your project
COPY . /app

# Ensure deps are synced after full copy
RUN uv sync

# Docker entrypoint wrapper (uses package console scripts via uv environment)
COPY scripts/docker-entrypoint.sh /usr/local/bin/incident-triage-entrypoint
RUN chmod +x /usr/local/bin/incident-triage-entrypoint

# Create runtime directories and non-root user
RUN groupadd --system app && useradd --system --gid app --create-home app \
    && mkdir -p /data /evidence /runbooks \
    && chown -R app:app /app /data /evidence /runbooks

EXPOSE 3333

# Run MCP server in streamable-http mode on 0.0.0.0:3333
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=3333
ENV EVIDENCE_BACKEND=fs
ENV EVIDENCE_DIR=/evidence

USER app

ENTRYPOINT ["incident-triage-entrypoint"]
