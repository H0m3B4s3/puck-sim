"""FastAPI app assembly + dev-server entry point (DEVPLAN.md Step 2.9a).

Deliberately NOT a monolithic ``app.py`` with every route inlined (the shape DEVPLAN.md's Step
2.9 planning notes gesture at when citing HoopR's single 1082-line ``hoopsim/web/app.py``) --
this file only builds the ``FastAPI`` instance, wires middleware, and mounts routers from the
``web/routers/`` package. ``routers/career.py`` is the only router this step adds; later steps
(2.9b-i/ii/iii) add sibling router modules (``roster.py``, ``season.py``, ``transactions.py``)
and mount them here alongside ``career.router``, rather than growing one giant file.

CORS: PuckSim is a local, single-user, no-auth app (DESIGN.md) -- the frontend (a future Vite dev
server, DEVPLAN.md Step 2.10) and the backend run on different localhost ports during
development, so CORS has to be permissive enough to allow any localhost/127.0.0.1 port, with
credentials allowed since the session id travels as a cookie (``web/session.py``). This is
intentionally scoped to loopback origins only, not ``allow_origins=["*"]`` -- there's no public
deployment story for this app (DESIGN.md: "local single-user app... revisit only if you ever want
to share it with other people"), so there's no reason to accept CORS requests from anywhere else.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pucksim.web.routers import (
    career,
    league,
    offseason,
    players,
    playoffs,
    roster,
    season,
    transactions,
)

# Any localhost/127.0.0.1 origin, any port -- covers Vite's default dev-server port plus
# whatever port it picks if that one's already taken, without hardcoding a specific number.
_LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000


def create_app() -> FastAPI:
    """Build the FastAPI app: CORS middleware + every ``web/routers/`` router mounted."""
    app = FastAPI(
        title="PuckSim",
        description="Local NHL franchise simulation -- session/career web API.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_LOCAL_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(career.router)
    app.include_router(league.router)
    app.include_router(players.router)
    app.include_router(roster.router)
    app.include_router(season.router)
    app.include_router(transactions.router)
    app.include_router(playoffs.router)
    app.include_router(offseason.router)

    return app


# Module-level app instance -- what `uvicorn.run("pucksim.web.app:app", ...)` (in `run()` below)
# and any ASGI server / test client target.
app = create_app()


def run(host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT) -> None:
    """Start the dev server. Bound to the ``pucksim-web`` console-script entry point declared in
    ``pyproject.toml`` (``[project.scripts]``: ``pucksim-web = "pucksim.web.app:run"``) -- a
    zero-argument callable, so the defaults above are what running ``pucksim-web`` from a shell
    actually uses.
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
