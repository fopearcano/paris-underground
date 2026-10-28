"""Runtime settings, read once from environment variables.

Every default works without accounts, API keys or tokens. The basemap defaults to
the standard OpenStreetMap raster tiles; pedestrian routing defaults to the public
FOSSGIS OSRM foot profile. Both can be swapped for another key-free provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" '
    'rel="noopener noreferrer">OpenStreetMap</a> contributors'
)
FOSSGIS_FOOT_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/driving"

# Google Maps directions links accept an origin, a destination and at most nine
# waypoints, so a walking route is capped at eleven stops.
MAX_ROUTE_STOPS = 11


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _origin(url_template: str) -> str:
    """Return the scheme://host origin of a URL template, for the CSP.

    A `{s}` subdomain placeholder becomes a `*.` wildcard.
    """
    parts = urlsplit(url_template.replace("{s}.", "*."))
    return f"{parts.scheme}://{parts.netloc}"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8003
    tile_url: str = OSM_TILE_URL
    tile_attribution: str = OSM_ATTRIBUTION
    tile_max_zoom: int = 19
    routing_enabled: bool = True
    routing_url: str = FOSSGIS_FOOT_URL
    routing_timeout: float = 12.0
    routing_min_interval: float = 1.0
    user_agent: str = (
        f"ParisUndergroundAtlas/{__version__} "
        "(local historical atlas; +https://github.com/fopearcano/paris-underground)"
    )
    data_dir: Path = DATA_DIR

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("PU_HOST", cls.host),
            port=int(os.environ.get("PU_PORT", cls.port)),
            tile_url=os.environ.get("PU_TILE_URL", cls.tile_url),
            tile_attribution=os.environ.get("PU_TILE_ATTRIBUTION", cls.tile_attribution),
            tile_max_zoom=int(os.environ.get("PU_TILE_MAX_ZOOM", cls.tile_max_zoom)),
            routing_enabled=_env_bool("PU_ROUTING_ENABLED", cls.routing_enabled),
            routing_url=os.environ.get("PU_ROUTING_URL", cls.routing_url),
            data_dir=Path(os.environ.get("PU_DATA_DIR", str(DATA_DIR))),
        )

    @property
    def tile_origin(self) -> str:
        return _origin(self.tile_url)

    def content_security_policy(self) -> str:
        """CSP for the atlas page.

        Images may only come from this server and the configured tile host, so a
        stray reference to a keyed basemap (e.g. CARTO) is blocked outright.
        """
        return "; ".join(
            [
                "default-src 'self'",
                f"img-src 'self' data: {self.tile_origin}",
                "script-src 'self'",
                # Leaflet and the marker icons set inline style attributes.
                "style-src 'self' 'unsafe-inline'",
                "font-src 'self'",
                "connect-src 'self'",
                "object-src 'none'",
                "base-uri 'self'",
                "form-action 'none'",
                "frame-ancestors 'none'",
            ]
        )
