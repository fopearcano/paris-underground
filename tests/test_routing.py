"""Walking-route endpoint: validation, upstream handling, fallback signalling and caching."""

from __future__ import annotations

import time

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routing import WalkingRouter

from .conftest import FakeOSRM

WALK = "tonneau,mistral,caveau,beat-hotel,tabou,magots,flore,club-sg,moineau"


def make_client(fake: FakeOSRM, **settings) -> TestClient:
    config = Settings(**{"routing_min_interval": 0.0, **settings})
    return TestClient(create_app(config, router=WalkingRouter(config, transport=httpx.MockTransport(fake))))


def test_route_is_returned_with_distance_legs_and_geometry(client, fake_osrm):
    body = client.get(f"/api/walking-route?stops={WALK}").json()
    assert body["mode"] == "walking"
    assert body["distance_m"] == 800 and body["duration_s"] == 640
    assert len(body["legs"]) == 8
    assert body["legs"][0] == {"from": "tonneau", "to": "mistral", "distance_m": 100, "duration_s": 80}
    assert body["geometry"]["type"] == "LineString"
    assert "OpenStreetMap" in body["attribution"]["text"]


def test_upstream_request_uses_stop_coordinates_and_a_descriptive_user_agent(client, fake_osrm):
    client.get("/api/walking-route?stops=beat-hotel,tabou")
    request = fake_osrm.requests[0]
    assert request.url.host == "routing.openstreetmap.de"
    assert request.url.path.endswith("/2.342753,48.853847;2.339440,48.854720")
    assert request.url.params["geometries"] == "geojson"
    assert request.headers["user-agent"].startswith("ParisUndergroundAtlas/")


def test_results_are_cached(client, fake_osrm):
    first = client.get(f"/api/walking-route?stops={WALK}").json()
    second = client.get(f"/api/walking-route?stops={WALK}").json()
    assert len(fake_osrm.requests) == 1
    assert first["cached"] is False and second["cached"] is True


def test_rate_limit_spaces_upstream_requests():
    fake = FakeOSRM()
    with make_client(fake, routing_min_interval=0.4) as client:
        client.get("/api/walking-route?stops=beat-hotel,tabou")
        started = time.monotonic()
        client.get("/api/walking-route?stops=tabou,flore")
        assert time.monotonic() - started >= 0.35
    assert len(fake.requests) == 2


def test_validation(client, fake_osrm):
    assert client.get("/api/walking-route?stops=beat-hotel").status_code == 422
    assert client.get("/api/walking-route?stops=beat-hotel,beat-hotel").status_code == 422
    assert client.get("/api/walking-route?stops=beat-hotel,atlantis").status_code == 404
    too_many = ",".join(["beat-hotel", "mistral", "moineau", "tonneau", "tabou", "club-sg", "caveau", "flore", "magots", "breton", "bateau", "chat-noir"])
    assert client.get(f"/api/walking-route?stops={too_many}").status_code == 422
    assert fake_osrm.requests == []


def test_upstream_error_signals_the_illustrative_fallback():
    with make_client(FakeOSRM(status=502)) as client:
        response = client.get("/api/walking-route?stops=beat-hotel,tabou")
    assert response.status_code == 503
    assert response.json() == {"detail": "Routing service answered HTTP 502.", "fallback": "straight-line"}


def test_unreachable_upstream_signals_the_fallback():
    with make_client(FakeOSRM(exc=httpx.ConnectTimeout("timed out"))) as client:
        response = client.get("/api/walking-route?stops=beat-hotel,tabou")
    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"]


def test_no_route_found_signals_the_fallback():
    with make_client(FakeOSRM(payload={"code": "NoRoute", "routes": []})) as client:
        response = client.get("/api/walking-route?stops=beat-hotel,tabou")
    assert response.status_code == 503
    assert "NoRoute" in response.json()["detail"]


def test_failures_are_not_cached():
    fake = FakeOSRM(status=500)
    with make_client(fake) as client:
        client.get("/api/walking-route?stops=beat-hotel,tabou")
        client.get("/api/walking-route?stops=beat-hotel,tabou")
    assert len(fake.requests) == 2


def test_routing_can_be_disabled():
    fake = FakeOSRM()
    with make_client(fake, routing_enabled=False) as client:
        assert client.get("/api/atlas").json()["routing"]["enabled"] is False
        assert client.get("/api/walking-route?stops=beat-hotel,tabou").status_code == 503
    assert fake.requests == []
