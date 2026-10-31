from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shd_telemetry import FaultInjector, Telemetry, create_service_app

from . import __version__

logger = logging.getLogger("user_service")


class User(BaseModel):
    id: str
    name: str
    email: str
    status: Literal["active", "suspended"]


SEED_USERS: tuple[User, ...] = (
    User(id="u-1001", name="Ada Lovelace", email="ada@example.com", status="active"),
    User(id="u-1002", name="Alan Turing", email="alan@example.com", status="active"),
    User(id="u-1003", name="Grace Hopper", email="grace@example.com", status="active"),
    User(id="u-1004", name="Mallory Example", email="mallory@example.com", status="suspended"),
)


def create_app(telemetry: Telemetry, faults: FaultInjector | None = None) -> FastAPI:
    app = create_service_app(
        title="User service", version=__version__, telemetry=telemetry, faults=faults
    )
    users = {user.id: user for user in SEED_USERS}

    @app.get("/users/{user_id}", tags=["users"])
    async def get_user(user_id: str) -> User:
        user = users.get(user_id)
        if user is None:
            logger.info("user not found", extra={"user.id": user_id})
            raise HTTPException(status_code=404, detail="User not found")
        logger.info("user looked up", extra={"user.id": user_id, "user.status": user.status})
        return user

    return app
