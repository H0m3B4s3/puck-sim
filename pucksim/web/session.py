"""Cookie-based session-to-World mapping (DEVPLAN.md Step 2.9a).

PuckSim is a local, single-user app (DESIGN.md: "no accounts, auth, or database"), but the web
layer still needs *some* way to associate an HTTP request with "which career is this browser
tab playing" -- a browser can have more than one tab/session open even in a single-user local
deployment, and FastAPI serves requests concurrently. The shape here is a small, from-scratch
``SessionStore``: an in-memory ``dict`` of session-id -> :class:`~pucksim.models.world.World`,
guarded by a ``threading.Lock`` so concurrent requests never race on the dict itself. There is no
persistence beyond the process lifetime and no HoopR source to port directly for this file (HoopR
is a separate sibling project, not part of this repo) -- this is a clean-room FastAPI session
pattern sized for this app's actual needs (one dict, one lock, cookie-carried opaque ids), not a
port of anything.

Session id is a random UUID4 hex string, carried to the browser as an ``httponly`` cookie
(``SESSION_COOKIE_NAME``) set on the response by whichever endpoint first establishes a session
(``POST /career/new``, and ``POST /career/load`` when no session cookie is already present --
see ``routers/career.py``). Every other career endpoint reads the cookie back via the
``get_world``/``get_session_id`` FastAPI dependencies below and 404s cleanly if it's missing or
doesn't map to a stored World (expired session, server restart, or a stale/tampered cookie) --
this is treated as "no active career," not a server error.
"""
from __future__ import annotations

import threading
import uuid
from typing import Dict, Optional

from fastapi import HTTPException, Request, Response

from pucksim.models.world import World

SESSION_COOKIE_NAME = "pucksim_sid"

# 30 days -- long enough that a browser left open overnight doesn't lose its career, short
# enough not to accumulate cookies forever. Purely a client-side cookie lifetime; server-side
# the session lives exactly as long as the process (see SessionStore's docstring).
_COOKIE_MAX_AGE_SECS = 60 * 60 * 24 * 30

_NO_SESSION_DETAIL = "no active session -- start a career via POST /career/new (or load a save via POST /career/load)"


class SessionNotFoundError(Exception):
    """Raised by ``SessionStore.get()`` when ``sid`` has no associated World."""


class SessionStore:
    """In-memory session-id -> World store, guarded by a lock for thread-safety.

    FastAPI/uvicorn can serve requests concurrently (even for a local single-user app, multiple
    browser tabs or an in-flight request racing a save/load), so every read/write against the
    backing dict takes ``self._lock``. World objects themselves are not safe to mutate from two
    threads at once, but this store only guards the *mapping* -- callers are still expected to
    treat "the World for a given sid" as owned by whichever request is currently handling it,
    same single-threaded-per-request assumption any synchronous FastAPI route makes.
    """

    def __init__(self) -> None:
        self._worlds: Dict[str, World] = {}
        self._lock = threading.Lock()

    def create(self, world: World) -> str:
        """Register ``world`` under a fresh session id, returning that id."""
        sid = uuid.uuid4().hex
        with self._lock:
            self._worlds[sid] = world
        return sid

    def get(self, sid: str) -> World:
        """Look up the World for ``sid``. Raises ``SessionNotFoundError`` if unknown."""
        with self._lock:
            world = self._worlds.get(sid)
        if world is None:
            raise SessionNotFoundError(f"no session found for sid={sid!r}")
        return world

    def save(self, sid: str, world: World) -> None:
        """Replace (or set) the World stored under ``sid`` -- used by load/advance endpoints
        that mutate or swap out a session's World in place."""
        with self._lock:
            self._worlds[sid] = world

    def exists(self, sid: str) -> bool:
        with self._lock:
            return sid in self._worlds

    def delete(self, sid: str) -> None:
        with self._lock:
            self._worlds.pop(sid, None)


# Module-level singleton: one process == one in-memory session table, matching DESIGN.md's
# "local single-user app... no database" deployment model. Routers import this directly rather
# than each constructing their own store.
session_store = SessionStore()


# ---------------------------------------------------------------------------
# Cookie helpers / FastAPI dependencies
# ---------------------------------------------------------------------------
def set_session_cookie(response: Response, sid: str) -> None:
    """Attach the session cookie to ``response``. Called by whichever endpoint establishes or
    re-establishes a session (new career, or load-with-no-prior-session)."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sid,
        max_age=_COOKIE_MAX_AGE_SECS,
        httponly=True,
        samesite="lax",
    )


def get_session_id_optional(request: Request) -> Optional[str]:
    """FastAPI dependency: the current request's session id if the cookie is present *and*
    still maps to a stored World, else ``None``. Never raises -- for endpoints that are legal
    to call with or without a pre-existing session (``POST /career/new``, ``POST
    /career/load``)."""
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if sid is not None and session_store.exists(sid):
        return sid
    return None


def get_session_id(request: Request) -> str:
    """FastAPI dependency: the current request's session id. Raises a clean 404 if the cookie
    is missing or unknown -- for endpoints that require an already-active career."""
    sid = get_session_id_optional(request)
    if sid is None:
        raise HTTPException(status_code=404, detail=_NO_SESSION_DETAIL)
    return sid


def get_world(request: Request) -> World:
    """FastAPI dependency: the current request's session World. Raises a clean 404 (not a
    500) if there's no active session -- callers should treat this the same as "no career in
    progress" everywhere in the API."""
    sid = get_session_id(request)
    try:
        return session_store.get(sid)
    except SessionNotFoundError as exc:  # pragma: no cover -- get_session_id already checked
        raise HTTPException(status_code=404, detail=_NO_SESSION_DETAIL) from exc
