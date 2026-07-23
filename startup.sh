#!/bin/bash
# Azure App Service (Linux, Python) startup command.
# Note: SSE + in-memory state require a single worker.
# Azure sets PORT in the container; fall back to 8000 for local use.
gunicorn \
  --bind=0.0.0.0:${PORT:-8000} \
  --workers=1 \
  --worker-class=uvicorn.workers.UvicornWorker \
  --timeout=600 \
  --keep-alive=75 \
  main:app
