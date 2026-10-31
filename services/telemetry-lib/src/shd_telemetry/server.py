"""Uvicorn runner with graceful, readiness-aware shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from types import FrameType

import uvicorn
from fastapi import FastAPI

from .runtime import ServiceRuntime

logger = logging.getLogger("shd.server")


class DrainingServer(uvicorn.Server):
    """On SIGTERM: fail ``/readyz``, keep serving for ``drain_seconds``, then shut down.

    The drain window lets Kubernetes remove the pod from Service endpoints before the listener
    closes; uvicorn then finishes in-flight requests (``timeout_graceful_shutdown``). A second
    signal skips the remaining drain.
    """

    def __init__(self, config: uvicorn.Config, runtime: ServiceRuntime, drain_seconds: float):
        super().__init__(config)
        self.runtime = runtime
        self.drain_seconds = drain_seconds
        self.drain_deadline: float | None = None

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if sig == signal.SIGTERM and self.drain_deadline is None and self.drain_seconds > 0:
            self._captured_signals.append(sig)
            self.runtime.lifecycle.draining = True
            self.drain_deadline = time.monotonic() + self.drain_seconds
            logger.info("SIGTERM received, draining", extra={"drain_seconds": self.drain_seconds})
            return
        self.runtime.lifecycle.draining = True
        super().handle_exit(sig, frame)

    async def on_tick(self, counter: int) -> bool:
        if self.drain_deadline is not None and time.monotonic() >= self.drain_deadline:
            self.should_exit = True
        return await super().on_tick(counter)

    async def shutdown(self, sockets=None) -> None:
        await super().shutdown(sockets)
        # uvicorn re-raises the captured signal after serve() returns, so flush telemetry here.
        await asyncio.to_thread(self.runtime.telemetry.shutdown)


def serve(app: FastAPI) -> None:
    runtime: ServiceRuntime = app.state.runtime
    config = uvicorn.Config(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),  # noqa: S104 - containers must listen on all interfaces
        port=int(os.environ.get("PORT", "8080")),
        log_config=None,  # keep the JSON root handler
        access_log=False,  # AccessLogMiddleware logs inside the trace context instead
        timeout_graceful_shutdown=int(os.environ.get("SHUTDOWN_TIMEOUT_SECONDS", "10")),
        server_header=False,
    )
    DrainingServer(
        config, runtime, drain_seconds=float(os.environ.get("SHUTDOWN_DRAIN_SECONDS", "5"))
    ).run()
