# RETCON app image: the UI/API server, the MCP server and the demo agents. FalkorDB is a separate service.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RETCON_EMBEDDER=hash \
    RETCON_HOST=0.0.0.0

WORKDIR /app
COPY . /app
# Runtime dependencies only (falkordb, mcp, numpy). The real embedding model (".[embed]") pulls in
# PyTorch and is optional; the demo, the benchmark and the replayed Gemini run use the offline hash embedder.
RUN python -m pip install -e . \
 && useradd --create-home --uid 10001 retcon \
 && chown -R retcon /app
USER retcon

EXPOSE 8200
HEALTHCHECK --interval=10s --timeout=4s --start-period=10s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8200/api/graphs', timeout=3).status == 200 else 1)"
CMD ["python", "-m", "ui.shell.server", "--port", "8200"]
