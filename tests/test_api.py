"""HTTP API, page delivery, security headers and the 'no keyed basemap' guarantees."""

from __future__ import annotations

import html as htmllib
import re

from app.config import STATIC_DIR, TEMPLATES_DIR, Settings

# Basemap/tile services that need accounts or keys. None may appear in the front end.
KEYED_PROVIDERS = ("cartocdn", "basemaps.carto", "mapbox", "stadiamaps", "thunderforest", "maptiler", "here.com", "googleapis.com/maps")
CREDENTIAL_MARKERS = re.compile(r"api[_-]?key|access[_-]?token|apikey", re.IGNORECASE)


def test_index_is_served_over_http(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = htmllib.unescape(response.text)
    assert "<span>Under</span>" in html  # PARIS / UNDER (yellow) / GROUND.
    assert "From Montmartre's bohemia to the Beat Hotel" in html
    # Everything is loaded from this server: no CDN, no Google Fonts.
    for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert ref.startswith(("/", "#")), ref


def test_head_request_on_index(client):
    assert client.head("/").status_code == 200


def test_security_and_referrer_headers(client):
    response = client.get("/")
    # OpenStreetMap's tile policy requires a Referer from web pages.
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = response.headers["content-security-policy"]
    assert "img-src 'self' data: https://tile.openstreetmap.org" in csp
    assert "script-src 'self'" in csp
    assert "carto" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"


def test_csp_follows_a_configured_tile_provider():
    custom = Settings(tile_url="https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png")
    assert "img-src 'self' data: https://*.tile.openstreetmap.fr" in custom.content_security_policy()


def test_static_assets_are_local(client):
    for path, kind in [
        ("/static/vendor/leaflet/leaflet.js", "javascript"),
        ("/static/vendor/leaflet/leaflet.css", "css"),
        ("/static/vendor/leaflet.markercluster/leaflet.markercluster.js", "javascript"),
        ("/static/js/main.js", "javascript"),
        ("/static/css/app.css", "css"),
        ("/static/fonts/space-grotesk-latin-wght-normal.woff2", "font/woff2"),
        ("/static/fonts/dm-sans-latin-wght-normal.woff2", "font/woff2"),
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert kind in response.headers["content-type"], (path, response.headers["content-type"])


def test_no_keyed_basemaps_or_credentials_in_the_front_end():
    files = [p for p in [*STATIC_DIR.rglob("*"), *TEMPLATES_DIR.rglob("*")]
             if p.suffix in {".js", ".css", ".html"} and "vendor" not in p.parts]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        for provider in KEYED_PROVIDERS:
            assert provider not in text, f"{provider} referenced in {path}"
        assert not CREDENTIAL_MARKERS.search(text), f"credential-like string in {path}"


def test_default_tile_url_is_standard_osm():
    assert Settings().tile_url == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["locations"] == 33


def test_atlas_bundle(client):
    body = client.get("/api/atlas").json()
    assert len(body["locations"]) == 33
    assert body["timeline"]["start"] == 1881 and body["timeline"]["end"] == 1968
    assert body["map"]["tile_url"].startswith("https://tile.openstreetmap.org/")
    assert "OpenStreetMap" in body["map"]["tile_attribution"]
    assert body["routing"] == {"enabled": True, "max_stops": 11}
    numbers = [loc["number"] for loc in body["locations"]]
    assert numbers == list(range(1, 34))
    beat = body["locations"][0]
    assert beat["groups"] == ["beat"]
    assert beat["address"]["full"] == "9 rue Gît-le-Cœur, 75006 Paris"
    active = [g["id"] for g in body["groups"] if g["count"]]
    assert active == ["beat", "jazz-existentialism", "lettrist-situationist", "surrealism", "montmartre-boheme",
                      "popular-paris", "lost-generation", "subterranean", "may-1968"]
    assert {q["id"]: q["count"] for q in body["quarters"]} == {
        "montmartre-pigalle": 9, "latin-quarter": 11, "saint-germain": 5,
        "belleville": 3, "menilmontant": 3, "denfert-rochereau": 2}
    assert all(loc["quarter"] and loc["then"] for loc in body["locations"])


def test_single_location(client):
    body = client.get("/api/locations/breton").json()
    assert body["name"] == "André Breton’s studio"
    assert body["number"] == 10
    assert client.get("/api/locations/nowhere").status_code == 404


def test_quarters(client):
    quarters = client.get("/api/quarters").json()
    belleville = next(q for q in quarters if q["id"] == "belleville")
    assert belleville["name"] == "Belleville" and belleville["count"] == 3
    assert "Willy Ronis" in belleville["then"] and "Parc de Belleville" in belleville["now"]


def test_movements_and_itineraries(client):
    assert len(client.get("/api/movements").json()["groups"]) == 10
    walks = client.get("/api/itineraries").json()
    assert [w["id"] for w in walks] == ["left-bank", "montmartre-pigalle", "latin-quarter-1968", "belleville-menilmontant"]
    assert walks[0]["stops"] == ["tonneau", "mistral", "caveau", "beat-hotel", "tabou", "magots", "flore", "club-sg", "moineau"]
