import signal

import pytest
import uvicorn
from fastapi import FastAPI

from shd_telemetry import DrainingServer, create_service_app
from shd_telemetry.testing import in_memory_telemetry

pytestmark = pytest.mark.anyio


def _server(drain_seconds: float) -> tuple[DrainingServer, FastAPI]:
    app = create_service_app(title="t", version="t", telemetry=in_memory_telemetry("t").telemetry)
    server = DrainingServer(uvicorn.Config(app), app.state.runtime, drain_seconds=drain_seconds)
    return server, app


async def test_sigterm_drains_before_exit():
    server, app = _server(drain_seconds=30)
    lifecycle = app.state.runtime.lifecycle
    lifecycle.started = True

    server.handle_exit(signal.SIGTERM, None)

    assert lifecycle.draining, "readiness must fail first"
    assert not server.should_exit, "keep serving during the drain window"
    assert await server.on_tick(1) is False

    server.drain_deadline = 0.0  # drain window elapsed
    assert await server.on_tick(1) is True


async def test_second_signal_skips_drain():
    server, _ = _server(drain_seconds=30)
    server.handle_exit(signal.SIGTERM, None)
    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit


async def test_sigint_or_zero_drain_exits_immediately():
    server, app = _server(drain_seconds=0)
    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit
    assert app.state.runtime.lifecycle.draining

    server, _ = _server(drain_seconds=30)
    server.handle_exit(signal.SIGINT, None)
    assert server.should_exit
