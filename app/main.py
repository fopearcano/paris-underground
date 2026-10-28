"""FastAPI application: serves the atlas page, its static assets and a small JSON API."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .config import MAX_ROUTE_STOPS, STATIC_DIR, TEMPLATES_DIR, Settings
from .routing import RoutingUnavailable, WalkingRouter
from .store import AtlasStore


def _asset_version() -> str:
    """Cache-busting token that changes whenever a static file changes."""
    stamp = max((p.stat().st_mtime_ns for p in STATIC_DIR.rglob("*") if p.is_file()), default=0)
    return hashlib.sha1(f"{__version__}:{stamp}".encode()).hexdigest()[:10]


def create_app(settings: Settings | None = None, router: WalkingRouter | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = AtlasStore.load(settings.data_dir)
    router = router or WalkingRouter(settings)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    asset_version = _asset_version()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await router.aclose()

    app = FastAPI(
        title="Paris Underground",
        version=__version__,
        description="Historical atlas of underground Paris, 1881–1968.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.router = router

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # OpenStreetMap's tile policy requires a Referer from web pages; this
        # policy sends just the origin (http://127.0.0.1:8003/) to tile servers.
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request,
            "index.html",
            {"v": asset_version, "meta": store.meta, "version": __version__},
        )
        response.headers["Content-Security-Policy"] = settings.content_security_policy()
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "locations": len(store.locations),
            "tiles": settings.tile_url,
            "routing": settings.routing_url if router.enabled else None,
        }

    @app.get("/api/atlas", tags=["atlas"])
    async def atlas() -> dict[str, Any]:
        """Everything the front end needs, in one request."""
        start, end = store.timeline_bounds()
        timeline = store.meta.timeline.model_dump()
        timeline.update(start=start, end=end)
        return {
            "meta": {
                "title": store.meta.title,
                "subtitle": store.meta.subtitle,
                "kicker": store.meta.kicker,
                "field_notes": store.meta.field_notes.model_dump(),
                "last_reviewed": store.meta.last_reviewed,
                "version": __version__,
            },
            "timeline": timeline,
            "map": {
                **store.meta.map.model_dump(),
                "tile_url": settings.tile_url,
                "tile_attribution": settings.tile_attribution,
                "tile_max_zoom": settings.tile_max_zoom,
            },
            "routing": {"enabled": router.enabled, "max_stops": MAX_ROUTE_STOPS},
            "groups": store.groups_payload(),
            "movements": [m.model_dump() for m in store.movements],
            "locations": store.locations_payload(),
            "itineraries": [i.model_dump() for i in store.itineraries],
        }

    @app.get("/api/locations", tags=["atlas"])
    async def locations() -> list[dict[str, Any]]:
        return store.locations_payload()

    @app.get("/api/locations/{location_id}", tags=["atlas"])
    async def location(location_id: str) -> dict[str, Any]:
        for number, loc in enumerate(store.locations, start=1):
            if loc.id == location_id:
                return store.location_payload(loc, number)
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'.")

    @app.get("/api/movements", tags=["atlas"])
    async def movements() -> dict[str, Any]:
        return {
            "groups": store.groups_payload(),
            "movements": [m.model_dump() for m in store.movements],
        }

    @app.get("/api/itineraries", tags=["atlas"])
    async def itineraries() -> list[dict[str, Any]]:
        return [i.model_dump() for i in store.itineraries]

    @app.get("/api/walking-route", tags=["routing"])
    async def walking_route(
        stops: Annotated[str, Query(description="Comma-separated location IDs, in walking order.")],
    ):
        ids = [s.strip() for s in stops.split(",") if s.strip()]
        if not 2 <= len(ids) <= MAX_ROUTE_STOPS:
            raise HTTPException(422, f"A walking route needs between 2 and {MAX_ROUTE_STOPS} stops.")
        if len(set(ids)) != len(ids):
            raise HTTPException(422, "A walking route cannot visit the same stop twice.")
        unknown = [i for i in ids if store.location(i) is None]
        if unknown:
            raise HTTPException(404, f"Unknown location(s): {', '.join(unknown)}.")
        try:
            return await router.route([store.location(i) for i in ids])
        except RoutingUnavailable as exc:
            # The front end falls back to an explicitly illustrative straight-line sketch.
            return JSONResponse(
                status_code=503,
                content={"detail": str(exc), "fallback": "straight-line"},
                headers={"Cache-Control": "no-store"},
            )

    return app


app = create_app()
