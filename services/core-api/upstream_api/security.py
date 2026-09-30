"""Role-based access for the MVP (PRD 14.3): signed JWTs with a static key.

Production puts Keycloak (OIDC) in front and this module then verifies its tokens
instead; the roles and the route rules below stay as they are (docs/SECURITY.md).
PRD 17 defers Keycloak to the pilot.

What is protected, and why the rest is not:

* officer    - sign-off, retraction, lab results: acts with authority over evidence.
* agency     - machine feeds (sensor, rainfall, overflow), the recurring-source report,
               research exports.
* public_health - the three /clinical routes the health zone calls (GC-7).
* admin      - everything.

Reads of beliefs, episodes and the network are public, as are a volunteer's own
actions (reporting, taking a mission): the web app has no login in the MVP, and a
volunteer is identified by the id they chose, not an account. Public reads therefore
carry no personal detail - see `redact_evidence`.

Fails closed: a token presented while no signing key is configured is refused (503),
never accepted.

    python -m upstream_api.security mint --sub clinical-stats --role public_health
"""
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException

from .config import settings

ROLES = frozenset({"citizen", "officer", "agency", "public_health", "clinician", "admin"})
ALGORITHM = "HS256"
# Who may see a report's observer and photo: the people who act on it (PRD 14.2).
EVIDENCE_DETAIL_ROLES = frozenset({"officer", "agency", "admin"})
_PERSONAL = ("observer_id", "photo_uri", "retracted_by")


@dataclass(frozen=True)
class Principal:
    sub: str
    roles: frozenset[str]

    def has_any(self, roles) -> bool:
        return "admin" in self.roles or bool(self.roles & set(roles))


def mint(sub: str, roles: list[str], *, ttl: dt.timedelta = dt.timedelta(days=30),
         key: str | None = None) -> str:
    unknown = set(roles) - ROLES
    if unknown:
        raise ValueError(f"unknown roles: {sorted(unknown)}")
    key = key if key is not None else settings.jwt_signing_key
    if not key:
        raise RuntimeError("JWT_SIGNING_KEY is not set")
    now = dt.datetime.now(dt.UTC)
    return jwt.encode({"sub": sub, "roles": sorted(roles), "iat": now, "exp": now + ttl},
                      key, algorithm=ALGORITHM)


def current_principal(authorization: str | None = Header(default=None)) -> Principal | None:
    """The caller, or None for an anonymous request. A bad token is an error, not None."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "expected a Bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    if not settings.jwt_signing_key:
        raise HTTPException(503, "authentication is not configured on this server")
    try:
        claims = jwt.decode(token, settings.jwt_signing_key, algorithms=[ALGORITHM],
                            options={"require": ["exp", "sub"]})
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}",
                            headers={"WWW-Authenticate": "Bearer"}) from e
    return Principal(str(claims["sub"]), frozenset(claims.get("roles") or []) & ROLES)


# The caller or None, as a route parameter type.
MaybePrincipal = Annotated["Principal | None", Depends(current_principal)]


def require_roles(*roles: str):
    """A route dependency: the caller must hold one of `roles` (admin always may)."""
    unknown = set(roles) - ROLES
    if unknown:
        raise ValueError(f"unknown roles: {sorted(unknown)}")

    def _check(principal: MaybePrincipal) -> Principal:
        if principal is None:
            raise HTTPException(401, "authentication required",
                                headers={"WWW-Authenticate": "Bearer"})
        if not principal.has_any(roles):
            raise HTTPException(403, f"requires one of: {', '.join(sorted(roles))}")
        return principal

    return _check


def redact_evidence(payload: dict, principal: Principal | None) -> dict:
    """PRD 14.2: who reported, and their photo, only for those who act on it.

    Photos are also withheld because nothing in the MVP screens them for faces or
    number plates; until something does, no photo is shown publicly at all.
    """
    if principal is not None and principal.has_any(EVIDENCE_DETAIL_ROLES):
        return payload
    return {k: v for k, v in payload.items() if k not in _PERSONAL}


def main() -> None:
    ap = argparse.ArgumentParser(description="Mint an MVP access token.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mint")
    m.add_argument("--sub", required=True, help="who the token is for")
    m.add_argument("--role", action="append", required=True, choices=sorted(ROLES))
    m.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    print(mint(a.sub, a.role, ttl=dt.timedelta(days=a.days)))


if __name__ == "__main__":
    main()
