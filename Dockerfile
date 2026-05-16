FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first (cached layer — only re-runs when pyproject.toml changes)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --no-dev

# Copy source and install the project itself
COPY . .
RUN uv sync --no-dev

# Runtime env — pass real values at `docker run` time via -e or --env-file
ENV TURSO_URL=""
ENV TURSO_AUTH_TOKEN=""
ENV GOOGLE_API_KEY=""
ENV LLM_MODEL="gemini-2.0-flash"
ENV DB_PATH="/app/healthquest.db"

EXPOSE 8000

CMD ["uv", "run", "fastmcp", "run", "fastmcp.json", \
     "--transport", "sse", \
     "--host", "0.0.0.0", \
     "--port", "8000"]
