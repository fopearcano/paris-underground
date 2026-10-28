"""Pedestrian routing through a key-free OSRM server (FOSSGIS foot profile by default).

The browser never talks to the routing server directly: the backend only accepts
location IDs from the atlas (never arbitrary coordinates), identifies itself with
a descriptive User-Agent, keeps to the provider's one-request-per-second policy
and caches results, so a walk is normally routed once per server run.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

import httpx

from .config import Settings
from .models import Location

ATTRIBUTION = {
    "text": "Walking route: FOSSGIS OSRM foot profile · Data © OpenStreetMap contributors",
    "provider_url": "https://routing.openstreetmap.de/about.html",
    "fix_the_map_url": "https://www.openstreetmap.org/fixthemap",
}


class RoutingUnavailable(RuntimeError):
    """The routing service could not produce a walking route."""


class WalkingRouter:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_size: int = 64,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._cache: OrderedDict[tuple[str, ...], dict[str, Any]] = OrderedDict()
        self._cache_size = cache_size
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self.upstream_requests = 0

    @property
    def enabled(self) -> bool:
        return self._settings.routing_enabled

    def _http(self) -> httpx.AsyncClient:
        # Created lazily so the client binds to the server's running event loop.
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.routing_timeout,
                headers={"User-Agent": self._settings.user_agent, "Accept": "application/json"},
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def route(self, stops: list[Location]) -> dict[str, Any]:
        if not self.enabled:
            raise RoutingUnavailable("Pedestrian routing is disabled on this server.")
        key = tuple(loc.id for loc in stops)
        if key in self._cache:
            self._cache.move_to_end(key)
            return {**self._cache[key], "cached": True}

        async with self._lock:
            if key in self._cache:  # filled while we waited for the lock
                return {**self._cache[key], "cached": True}
            wait = self._settings.routing_min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                payload = await self._fetch(stops)
            finally:
                self._last_request = time.monotonic()

        result = self._parse(payload, stops)
        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return {**result, "cached": False}

    async def _fetch(self, stops: list[Location]) -> dict[str, Any]:
        coords = ";".join(f"{s.coordinates.lng:.6f},{s.coordinates.lat:.6f}" for s in stops)
        url = f"{self._settings.routing_url.rstrip('/')}/{coords}"
        params = {"overview": "full", "geometries": "geojson", "steps": "false"}
        self.upstream_requests += 1
        try:
            response = await self._http().get(url, params=params)
        except httpx.HTTPError as exc:
            raise RoutingUnavailable(f"Routing service unreachable ({type(exc).__name__}).") from exc
        if response.status_code != 200:
            raise RoutingUnavailable(f"Routing service answered HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise RoutingUnavailable("Routing service returned invalid JSON.") from exc

    @staticmethod
    def _parse(payload: dict[str, Any], stops: list[Location]) -> dict[str, Any]:
        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RoutingUnavailable(f"Routing service found no route ({payload.get('code', 'no code')}).")
        route = payload["routes"][0]
        geometry = route.get("geometry") or {}
        legs = route.get("legs") or []
        if geometry.get("type") != "LineString" or len(legs) != len(stops) - 1:
            raise RoutingUnavailable("Routing service returned an unexpected route shape.")
        return {
            "mode": "walking",
            "provider": "FOSSGIS OSRM (foot profile)",
            "stops": [s.id for s in stops],
            "distance_m": round(route["distance"]),
            "duration_s": round(route["duration"]),
            "legs": [
                {
                    "from": a.id,
                    "to": b.id,
                    "distance_m": round(leg["distance"]),
                    "duration_s": round(leg["duration"]),
                }
                for a, b, leg in zip(stops, stops[1:], legs)
            ],
            "geometry": geometry,
            "attribution": ATTRIBUTION,
        }
