from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from shd_telemetry import (
    AuthSettings,
    FaultInjector,
    Principal,
    Telemetry,
    audit_user,
    authorize,
    create_service_app,
    current_principal,
)

from . import __version__

logger = logging.getLogger("user_service")


class User(BaseModel):
    id: str
    name: str
    email: str
    status: Literal["active", "suspended"]


# Client role of the user-service client in Keycloak's customers realm: look up any profile. Held by
# the order service's and the load generator's service accounts; customers only see their own.
USERS_READ = ("user-service", "users:read")

SEED_USERS: tuple[User, ...] = (
    User(id="u-1001", name="Ada Lovelace", email="ada@example.com", status="active"),
    User(id="u-1002", name="Alan Turing", email="alan@example.com", status="active"),
    User(id="u-1003", name="Grace Hopper", email="grace@example.com", status="active"),
    User(id="u-1004", name="Mallory Example", email="mallory@example.com", status="suspended"),
)


def create_app(
    telemetry: Telemetry,
    faults: FaultInjector | None = None,
    auth: AuthSettings | None = None,
    jwks_transport=None,
) -> FastAPI:
    app = create_service_app(
        title="User service",
        version=__version__,
        telemetry=telemetry,
        faults=faults,
        auth=auth,
        jwks_transport=jwks_transport,
    )
    users = {user.id: user for user in SEED_USERS}

    @app.get("/users/me", tags=["users"])
    async def get_me(
        request: Request, principal: Annotated[Principal, Depends(current_principal)]
    ) -> User:
        """The signed-in customer's profile. Created on first use from the token (just-in-time
        provisioning): customers who registered in Keycloak need no separate sign-up here."""
        if not principal.authenticated:
            raise HTTPException(404, "No signed-in customer")
        authorize(
            request, principal, not principal.is_service_account, "only customers have a profile"
        )
        user = users.get(principal.subject)
        if user is None:
            user = User(
                id=principal.subject,
                name=principal.name or principal.username or principal.subject,
                email=principal.email or "",
                status="active",
            )
            users[user.id] = user
            logger.info("user provisioned", extra={"user.id": user.id})
        return user

    @app.get("/users/{user_id}", tags=["users"])
    async def get_user(
        user_id: str,
        request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> User:
        authorize(
            request,
            principal,
            principal.has_client_role(*USERS_READ)
            or (not principal.is_service_account and principal.subject == user_id),
            "customers can only read their own profile",
        )
        user = users.get(user_id)
        if user is None:
            logger.info("user not found", extra={"user.id": user_id})
            raise HTTPException(status_code=404, detail="User not found")
        logger.info(
            "user looked up",
            extra={
                "user.id": user_id,
                "user.status": user.status,
                "oauth.client_id": principal.client_id,
                "enduser.id": audit_user(request, principal),
            },
        )
        return user

    return app
