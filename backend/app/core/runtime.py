"""Event loop policy setup.

psycopg's async driver cannot run on Windows' default ``ProactorEventLoop`` and raises
``InterfaceError`` on the first connection. Windows needs the selector loop instead.

This must be called *before* the event loop is created, so it belongs in each entry point
(local runner, ingestion CLI, test session) rather than in an imported module — under
``uvicorn app.main:app`` the app is imported after the loop already exists. Inside Docker
the app runs on Linux, where this is a no-op.
"""

from __future__ import annotations

import asyncio
import sys


def configure_event_loop_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
