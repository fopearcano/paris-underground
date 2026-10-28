from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR, Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.routing import WalkingRouter  # noqa: E402

ARTIFACTS = ROOT / "tests" / "artifacts"


def load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def osrm_response(n_stops: int) -> dict:
    """A minimal OSRM-shaped answer with `n_stops - 1` legs of 100 m each."""
    coords = [[2.34 + i * 0.001, 48.85] for i in range(n_stops)]
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 100.0 * (n_stops - 1),
                "duration": 80.0 * (n_stops - 1),
                "geometry": {"type": "LineString", "coordinates": coords},
                "legs": [{"distance": 100.0, "duration": 80.0} for _ in range(n_stops - 1)],
            }
        ],
    }


class FakeOSRM:
    """httpx transport standing in for the routing server; records every request."""

    def __init__(self, status: int = 200, payload: dict | None = None, exc: Exception | None = None):
        self.status, self.payload, self.exc = status, payload, exc
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.exc:
            raise self.exc
        n_stops = request.url.path.rsplit("/", 1)[-1].count(";") + 1
        return httpx.Response(self.status, json=self.payload or osrm_response(n_stops))


@pytest.fixture
def fake_osrm() -> FakeOSRM:
    return FakeOSRM()


@pytest.fixture
def settings() -> Settings:
    return Settings(routing_min_interval=0.0)


@pytest.fixture
def client(settings, fake_osrm):
    router = WalkingRouter(settings, transport=httpx.MockTransport(fake_osrm))
    with TestClient(create_app(settings, router=router)) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# End-to-end fixtures: a live uvicorn server and a Playwright browser.
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    """URL of the atlas under test: E2E_BASE_URL if set, else a fresh server."""
    if os.environ.get("E2E_BASE_URL"):
        yield os.environ["E2E_BASE_URL"].rstrip("/")
        return
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{url}/api/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError(f"Server exited early:\n{proc.stdout.read().decode()}")
                time.sleep(0.2)
        else:
            raise RuntimeError("Server did not start within 20 s")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api", reason="pip install -r requirements-dev.txt")
    channel = os.environ.get("E2E_BROWSER_CHANNEL") or None  # e.g. "chrome" for Google Chrome
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel=channel)
        except Exception as exc:  # browser binaries not installed
            pytest.skip(f"Chromium unavailable ({exc.__class__.__name__}); run: python -m playwright install chromium")
        yield browser
        browser.close()


@pytest.fixture
def artifacts() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS
