"""Run the API outside Docker.

    python run_local.py

Prefer this over calling ``uvicorn app.main:app`` directly, because it installs the
selector event loop policy that psycopg needs on Windows before the loop is created.
"""

from __future__ import annotations

import os

import uvicorn

from app.core.runtime import configure_event_loop_policy

if __name__ == "__main__":
    configure_event_loop_policy()
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD", "true").lower() == "true",
        log_config=None,  # structlog owns formatting; see app/core/logging.py
    )
