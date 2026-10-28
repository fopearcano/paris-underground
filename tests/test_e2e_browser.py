"""End-to-end tests in a real Chromium browser against a live server.

Run with:  python -m pytest tests/test_e2e_browser.py
Google Chrome instead of Playwright's Chromium:  E2E_BROWSER_CHANNEL=chrome python -m pytest ...
Against an already running server:  E2E_BASE_URL=http://127.0.0.1:8003 python -m pytest ...
Offline:  python -m pytest -m "not network"
"""

from __future__ import annotations

import hashlib
import io
import math
import time
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.e2e

# SHA-256 of tile images that look like a map tile but are error placeholders.
PLACEHOLDER_TILES = {
    "cc3f31364a735d9a8179af36b3db7617cdff8bdb0248654ebcc3df91607abedc": "CARTO 'API KEY REQUIRED' placeholder",
    "b02c44252dac5a5e820ecef1e9bf9200e9407c042df668a466a1aa81a9ecca7a": "OpenStreetMap 'Access blocked' tile",
}

ALL_IDS = ["beat-hotel", "mistral", "moineau", "tonneau", "tabou", "club-sg", "caveau", "flore", "magots", "breton", "bateau", "chat-noir"]
LEFT_BANK_WALK = ["tonneau", "mistral", "caveau", "beat-hotel", "tabou", "magots", "flore", "club-sg", "moineau"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def context(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-GB")
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    page = context.new_page()
    page.problems = []
    page.on("console", lambda m: page.problems.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    yield page
    page.close()


def open_atlas(page, base_url, path="/"):
    page.goto(base_url + path)
    page.wait_for_selector("html[data-ready='true']", timeout=15_000)


def wait_until(page, expression, timeout=10_000):
    """Poll a JS expression from Python. (wait_for_function uses eval, which the page's CSP forbids.)"""
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for: {expression}")


def wait_map_settled(page):
    settled = page.evaluate(
        """async () => {
            const map = window.__atlas.map;
            let last = '';
            for (let i = 0; i < 60; i++) {
              await new Promise((r) => setTimeout(r, 120));
              const c = map.getCenter();
              const key = `${c.lat.toFixed(6)},${c.lng.toFixed(6)},${map.getZoom()}`;
              if (key === last && !map._animatingZoom) return true;
              last = key;
            }
            return false;
        }"""
    )
    assert settled, "map never stopped moving"


def list_ids(page):
    return page.eval_on_selector_all("#place-list .place", "els => els.map((e) => e.dataset.id)")


def map_ids(page):
    return page.evaluate("window.__atlas.visibleIds()")


def shown_ids(page):
    """IDs in the list, checked against the markers the map is showing."""
    ids = list_ids(page)
    assert ids == map_ids(page), "list and map disagree"
    return ids


def markers_on_map(page) -> int:
    """Individual pins plus the locations folded into clusters."""
    return page.evaluate(
        """() => document.querySelectorAll('.leaflet-marker-pane .pu-pin').length +
            [...document.querySelectorAll('.leaflet-marker-pane .pu-cluster div')]
              .reduce((n, el) => n + parseInt(el.textContent, 10), 0)"""
    )


def wait_markers(page, expected, timeout=8_000):
    """Wait for cluster/marker animations to finish with `expected` locations shown."""
    deadline = time.monotonic() + timeout / 1000
    while (count := markers_on_map(page)) != expected or page.locator(".leaflet-cluster-anim").count():
        if time.monotonic() > deadline:
            raise AssertionError(f"{count} locations on the map, expected {expected}")
        page.wait_for_timeout(100)


def settled_box(locator, timeout=5_000):
    """Bounding box once the element has stopped moving (markers animate out of clusters)."""
    deadline = time.monotonic() + timeout / 1000
    last = None
    while time.monotonic() < deadline:
        box = locator.bounding_box()
        if box and box == last:
            return box
        last = box
        locator.page.wait_for_timeout(120)
    raise AssertionError("element kept moving")


def metres_between(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def set_year(page, year):
    page.locator("#year").fill(str(year))


def colour_count(png: bytes) -> int:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    colours = image.getcolors(maxcolors=1 << 20)
    return len(colours) if colours else 1 << 20


def mean_brightness(png: bytes) -> float:
    from PIL import Image, ImageStat

    return ImageStat.Stat(Image.open(io.BytesIO(png)).convert("L")).mean[0]


# ---------------------------------------------------------------------------
# Loading, tiles and the "API KEY REQUIRED" regression
# ---------------------------------------------------------------------------


def test_page_loads_over_http_without_errors(page, base_url):
    hosts = set()
    page.on("request", lambda r: hosts.add(urlsplit(r.url).hostname))
    open_atlas(page, base_url)
    assert page.title().startswith("PARIS UNDERGROUND")
    assert page.inner_text("h1.wordmark").split() == ["PARIS", "UNDER", "GROUND."]
    assert page.eval_on_selector("h1.wordmark span", "e => getComputedStyle(e).color") == "rgb(242, 211, 91)"
    assert page.inner_text("#metric-locations") == "12"
    page.wait_for_timeout(1500)
    # Only this server and the OSM tile server: no CDN, no font service, no keyed basemap.
    assert hosts <= {urlsplit(base_url).hostname, "tile.openstreetmap.org"}, hosts
    assert page.problems == []


@pytest.mark.network
def test_basemap_tiles_visibly_load(page, base_url, artifacts):
    tiles = []
    page.on("response", lambda r: tiles.append(r) if "tile.openstreetmap.org" in r.url else None)
    open_atlas(page, base_url)
    wait_until(page, "document.querySelectorAll('img.leaflet-tile-loaded').length >= 8", timeout=30_000)
    wait_map_settled(page)

    ok = [r for r in tiles if r.status == 200]
    assert len(ok) >= 8, [(r.status, r.url) for r in tiles]
    counts = []
    for response in ok[:16]:
        assert response.headers["content-type"] == "image/png"
        body = response.body()
        digest = hashlib.sha256(body).hexdigest()
        assert digest not in PLACEHOLDER_TILES, f"{PLACEHOLDER_TILES[digest]}: {response.url}"
        counts.append(colour_count(body))
        # OSM's tile policy: requests must carry the page's Referer.
        assert response.request.all_headers().get("referer", "").startswith(base_url)
    assert sorted(counts)[len(counts) // 2] > 64, f"tiles look blank: colour counts {counts}"

    # The map pixels on screen are real cartography, not an empty or placeholder grid.
    shot = page.locator("#map").screenshot(path=str(artifacts / "basemap-night.png"))
    assert colour_count(shot) > 2000
    assert page.locator("#map-fallback").is_hidden()
    assert "API KEY" not in page.inner_text("body").upper()
    assert page.problems == []


def test_no_keyed_basemap_is_ever_requested(page, base_url):
    requested = []
    page.on("request", lambda r: requested.append(r.url))
    open_atlas(page, base_url)
    page.click("#mode-street")
    page.click("#mode-night")
    page.wait_for_timeout(1000)
    assert not [u for u in requested if "carto" in u or "apikey" in u.lower() or "access_token" in u]
    tile_srcs = page.eval_on_selector_all("img.leaflet-tile", "els => els.map((e) => e.src)")
    assert tile_srcs and all(s.startswith("https://tile.openstreetmap.org/") for s in tile_srcs)


def test_fallback_when_tiles_are_blocked(page, base_url):
    page.route("https://tile.openstreetmap.org/**", lambda route: route.abort("blockedbyclient"))
    open_atlas(page, base_url)
    page.wait_for_selector("#map-fallback:not([hidden])", timeout=15_000)
    assert page.inner_text("#map-fallback-title") == "Basemap tiles failed to load"
    assert "tile.openstreetmap.org" in page.inner_text("#map-fallback-text")
    assert page.locator("#map-area.tiles-down").count() == 1
    # Markers, list and details keep working without a basemap.
    wait_markers(page, 12)
    assert len(list_ids(page)) == 12
    page.click(".place[data-id='breton']")
    assert page.text_content("#detail-title") == "André Breton’s studio"


# ---------------------------------------------------------------------------
# Markers and selection
# ---------------------------------------------------------------------------


def test_all_twelve_markers_display_at_their_coordinates(page, base_url):
    open_atlas(page, base_url)
    wait_markers(page, 12)
    locations = page.evaluate("window.__atlas.atlas.locations.map((l) => ({ id: l.id, ...l.coordinates }))")
    assert [loc["id"] for loc in locations] == ALL_IDS
    map_box = page.locator("#map").bounding_box()
    for loc in locations:
        page.evaluate("([lat, lng]) => window.__atlas.map.setView([lat, lng], 18, { animate: false })", [loc["lat"], loc["lng"]])
        pin = page.locator(f".leaflet-marker-icon[data-id='{loc['id']}']")
        pin.wait_for(state="visible")
        box = settled_box(pin)
        centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        assert abs(centre[0] - (map_box["x"] + map_box["width"] / 2)) < 3, loc["id"]
        assert abs(centre[1] - (map_box["y"] + map_box["height"] / 2)) < 3, loc["id"]
        assert pin.get_attribute("aria-label").startswith(f"{ALL_IDS.index(loc['id']) + 1}. ")


def test_sidebar_selection_centres_map_and_opens_details(page, base_url):
    open_atlas(page, base_url)
    page.click(".place[data-id='beat-hotel']")
    wait_map_settled(page)
    assert page.text_content("#detail-title") == "The Beat Hotel"
    detail = page.text_content("#detail")
    for text in ["9 rue Gît-le-Cœur, Paris 6e", "Beat Generation", "1957–1963", "Allen Ginsberg",
                 "William S. Burroughs", "Gregory Corso", "Brion Gysin", "Today", "Repurposed"]:
        assert text in detail
    centre = page.evaluate("(() => { const c = window.__atlas.map.getCenter(); return { lat: c.lat, lng: c.lng }; })()")
    assert metres_between(centre, {"lat": 48.853847, "lng": 2.342753}) < 50
    assert page.locator(".leaflet-marker-icon[data-id='beat-hotel']").get_attribute("class").count("is-selected") == 1
    assert page.get_attribute(".place[data-id='beat-hotel']", "aria-current") == "true"
    assert page.url.endswith("#place=beat-hotel")

    # The detail panel leaves most of the map visible.
    map_box, detail_box = page.locator("#map").bounding_box(), page.locator("#detail").bounding_box()
    assert detail_box["width"] * detail_box["height"] < 0.4 * map_box["width"] * map_box["height"]

    # A marker that starts inside a cluster is revealed when selected.
    page.click(".place[data-id='flore']")
    wait_map_settled(page)
    assert page.locator(".leaflet-marker-icon[data-id='flore']").is_visible()


def test_keyboard_marker_activation_and_escape(page, base_url):
    open_atlas(page, base_url)
    page.focus(".leaflet-marker-icon[data-id='breton']")
    page.keyboard.press("Enter")
    page.wait_for_selector("#detail:not([hidden])")
    assert page.text_content("#detail-title") == "André Breton’s studio"
    page.keyboard.press("Escape")
    assert page.locator("#detail").is_hidden()
    page.keyboard.press("/")
    assert page.evaluate("document.activeElement.id") == "search"


def test_deep_link_opens_a_place(page, base_url):
    open_atlas(page, base_url, "/#place=chat-noir")
    assert page.text_content("#detail-title") == "Le Chat Noir (historical premises)"


# ---------------------------------------------------------------------------
# Filters, search and timeline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "group,expected",
    [
        ("beat", ["beat-hotel", "mistral"]),
        ("jazz-existentialism", ["tabou", "club-sg", "caveau", "flore", "magots"]),
        ("lettrist-situationist", ["moineau", "tonneau"]),
        ("surrealism", ["breton"]),
        ("montmartre-boheme", ["bateau", "chat-noir"]),
    ],
)
def test_movement_filters(page, base_url, group, expected):
    open_atlas(page, base_url)
    page.click(f".pill[data-group='{group}']")
    assert shown_ids(page) == expected
    assert page.get_attribute(f".pill[data-group='{group}']", "aria-pressed") == "true"
    assert page.text_content("#result-count") == f"{len(expected)} of 12 locations"
    wait_map_settled(page)
    wait_markers(page, len(expected))
    page.click("#clear-filters")
    assert shown_ids(page) == ALL_IDS


def test_filtering_out_the_selected_place_closes_its_panel(page, base_url):
    open_atlas(page, base_url)
    page.click(".place[data-id='beat-hotel']")
    page.locator("#detail").wait_for(state="visible")
    page.click(".pill[data-group='surrealism']")
    assert page.locator("#detail").is_hidden()
    assert page.get_attribute(".pill[data-group='surrealism']", "aria-pressed") == "true"
    assert page.get_attribute(".pill[data-group='all']", "aria-pressed") == "false"
    assert shown_ids(page) == ["breton"]
    assert "#place=" not in page.url
    set_year(page, 1958)
    assert page.text_content("#timeline-title") == "1958 · 1 place active"


def test_filter_pill_labels(page, base_url):
    open_atlas(page, base_url)
    labels = page.eval_on_selector_all(".pill .pill-label", "els => els.map((e) => e.textContent)")
    assert labels == ["All", "Beat Generation", "Jazz & Existentialism", "Lettrists & Situationists", "Surrealism", "Montmartre Bohème"]


def test_search(page, base_url):
    open_atlas(page, base_url)
    cases = {
        "Burroughs": ["beat-hotel"],
        "git le coeur": ["beat-hotel"],  # accents and ligatures are ignored
        "rue du Four": ["moineau"],  # street names
        "Vian": ["tabou", "club-sg", "flore"],  # people
        "situationist": ["moineau", "tonneau"],  # movements (via "Lettrists & Situationists")
        "shadow theatre": ["chat-noir"],  # descriptive keywords
        "picasso cubism": ["bateau"],
    }
    for query, expected in cases.items():
        page.fill("#search", query)
        assert shown_ids(page) == expected, query

    # Search and movement filters combine, and the query survives a filter change.
    page.fill("#search", "Vian")
    page.click(".pill[data-group='jazz-existentialism']")
    assert shown_ids(page) == ["tabou", "club-sg", "flore"]
    page.click(".pill[data-group='surrealism']")
    assert shown_ids(page) == []
    assert "No matching places" in page.inner_text("#place-list")
    assert page.input_value("#search") == "Vian"
    page.click("#clear-filters")
    assert page.input_value("#search") == ""
    assert shown_ids(page) == ALL_IDS


def test_timeline(page, base_url):
    open_atlas(page, base_url)
    expectations = {
        1881: [],
        1890: ["chat-noir"],
        1907: ["bateau"],
        1925: ["breton"],
        1942: ["flore", "breton"],
        1958: ["beat-hotel", "mistral", "tonneau", "club-sg", "caveau", "flore", "magots", "breton"],
        1965: ["caveau", "breton"],
    }
    for year, expected in expectations.items():
        set_year(page, year)
        assert shown_ids(page) == expected, year
    set_year(page, 1958)
    assert page.inner_text("#timeline-title") == "1958 · 8 places active"
    assert page.locator(".leaflet-marker-pane .pu-pin.in-period, .leaflet-marker-pane .pu-cluster").count() > 0

    # Timeline + movement filter.
    page.click(".pill[data-group='beat']")
    assert shown_ids(page) == ["beat-hotel", "mistral"]
    set_year(page, 1890)
    assert shown_ids(page) == []
    page.click("#timeline-all")
    assert shown_ids(page) == ["beat-hotel", "mistral"]
    assert page.inner_text("#timeline-title") == "All periods · 1881–1968"
    assert page.is_disabled("#timeline-all")


# ---------------------------------------------------------------------------
# Map styles
# ---------------------------------------------------------------------------


def test_night_filter_applies_to_tiles_only(page, base_url):
    open_atlas(page, base_url)
    style = """(sel) => getComputedStyle(document.querySelector(sel)).filter"""
    assert "invert" in page.evaluate(style, ".leaflet-tile-pane")
    for pane in [".leaflet-marker-pane", ".leaflet-overlay-pane", ".leaflet-tooltip-pane", ".leaflet-control-container", "#map"]:
        assert page.evaluate(style, pane) == "none", pane

    page.click("#mode-street")
    assert page.get_attribute("#mode-street", "aria-pressed") == "true"
    assert page.evaluate(style, ".leaflet-tile-pane") == "none"
    page.click("#mode-night")
    assert "invert" in page.evaluate(style, ".leaflet-tile-pane")


@pytest.mark.network
def test_night_and_street_render_differently(page, base_url, artifacts):
    open_atlas(page, base_url)
    wait_until(page, "document.querySelectorAll('img.leaflet-tile-loaded').length >= 8", timeout=30_000)
    wait_map_settled(page)
    night = page.locator("#map").screenshot(path=str(artifacts / "map-night.png"))
    page.click("#mode-street")
    page.wait_for_timeout(300)
    street = page.locator("#map").screenshot(path=str(artifacts / "map-street.png"))
    assert mean_brightness(street) > mean_brightness(night) + 60
    assert colour_count(street) > 2000


# ---------------------------------------------------------------------------
# Walking itinerary
# ---------------------------------------------------------------------------


def _google_dir_params(href):
    from urllib.parse import parse_qs

    parts = urlsplit(href)
    assert (parts.netloc, parts.path) == ("www.google.com", "/maps/dir/")
    return {k: v[0] for k, v in parse_qs(parts.query).items()}


@pytest.mark.network
def test_walking_itinerary(page, base_url, artifacts):
    open_atlas(page, base_url)
    page.click("#route-cta")
    assert page.get_attribute("#tab-route", "aria-selected") == "true"
    stops = page.eval_on_selector_all(".route-stop", "els => els.map((e) => e.dataset.id)")
    assert stops == LEFT_BANK_WALK
    page.wait_for_selector(".route-status--routed, .route-status--fallback", timeout=25_000)
    assert page.locator(".route-status--routed").count() == 1, page.inner_text(".route-status")
    assert page.locator(".leaflet-overlay-pane path.route-line--routed").count() == 1
    distance = page.inner_text("#route-distance")
    assert distance.endswith(" km") and 1.5 < float(distance.split()[0]) < 4.0
    assert page.locator(".route-leg").count() == 8
    assert page.locator(".leaflet-marker-pane .pin-route").count() >= 1
    page.screenshot(path=str(artifacts / "walking-route.png"))

    params = _google_dir_params(page.get_attribute("#route-gmaps", "href"))
    assert params["travelmode"] == "walking"
    assert params["origin"] == "32 rue de la Montagne-Sainte-Geneviève, 75005 Paris, France"
    assert params["destination"] == "22 rue du Four, 75006 Paris, France"
    assert len(params["waypoints"].split("|")) == 7

    page.click("#route-clear")
    assert page.locator(".route-stop").count() == 0
    assert page.locator(".leaflet-overlay-pane path.route-line").count() == 0
    assert page.inner_text("#tab-route-count") == "0"


def test_routing_outage_is_labelled_illustrative(page, base_url):
    page.route("**/api/walking-route**", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body='{"detail": "Routing service unreachable (ConnectError).", "fallback": "straight-line"}'))
    open_atlas(page, base_url)
    page.click("#route-cta")
    status = page.locator("[data-route-mode='illustrative']")
    status.wait_for()
    assert "Illustrative route — not walking directions" in status.inner_text()
    assert page.locator("#route-distance").count() == 0  # no invented distance
    assert page.locator(".leaflet-overlay-pane path.route-line--illustrative").count() == 1


def test_building_a_custom_route_from_the_detail_panel(page, base_url):
    page.route("**/api/walking-route**", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail": "offline", "fallback": "straight-line"}'))
    open_atlas(page, base_url)
    page.click(".place[data-id='beat-hotel']")
    page.click("#detail-route")
    assert page.inner_text("#tab-route-count") == "1"
    assert "Route stop 1" in page.inner_text("#detail-route")
    page.click(".place[data-id='tabou']")
    page.click("#detail-route")
    assert page.inner_text("#tab-route-count") == "2"
    page.click("#tab-route")
    assert page.eval_on_selector_all(".route-stop", "els => els.map((e) => e.dataset.id)") == ["beat-hotel", "tabou"]
    page.click(".route-stop[data-id='tabou'] [aria-label^='Move'][aria-label$='earlier']")
    assert page.eval_on_selector_all(".route-stop", "els => els.map((e) => e.dataset.id)") == ["tabou", "beat-hotel"]
    assert page.locator(".leaflet-marker-pane .pin-route").count() >= 1


# ---------------------------------------------------------------------------
# External links
# ---------------------------------------------------------------------------


def test_external_links_open_in_new_tabs(page, context, base_url):
    # Answer external navigations locally: this checks the browser opens the right URL.
    def is_external(url):
        host = urlsplit(url).hostname or ""
        return host not in {urlsplit(base_url).hostname, "tile.openstreetmap.org"}

    context.route(is_external, lambda route: route.fulfill(status=200, content_type="text/html", body="<title>stub</title>"))
    open_atlas(page, base_url)
    page.click(".place[data-id='beat-hotel']")
    for selector, expected in [
        ("#detail-source", "https://www.centrepompidou.fr/en/program/calendar/event/c58Xyrx"),
        ("#detail-gmaps", "https://www.google.com/maps/search/?api=1&query=9%20rue%20G%C3%AEt-le-C%C5%93ur%2C%2075006%20Paris%2C%20France"),
    ]:
        link = page.locator(selector)
        assert link.get_attribute("target") == "_blank"
        assert "noopener" in link.get_attribute("rel")
        with page.expect_popup() as popup_info:
            link.click()
        popup = popup_info.value
        popup.wait_for_load_state()
        assert popup.url == expected
        popup.close()
    sources = page.eval_on_selector_all("#detail .sources a", "els => els.map((e) => [e.href, e.target])")
    assert sources and all(href.startswith("https://") and target == "_blank" for href, target in sources)


# ---------------------------------------------------------------------------
# Responsive layout
# ---------------------------------------------------------------------------


def test_desktop_sidebar_collapses(page, base_url):
    open_atlas(page, base_url)
    page.click("#sidebar-toggle")
    assert page.get_attribute("#app", "data-sidebar") == "closed"
    assert page.get_attribute("#sidebar-toggle", "aria-expanded") == "false"
    wait_until(page, "window.__atlas.map.getSize().x === window.innerWidth", timeout=5000)
    page.click("#sidebar-toggle")
    wait_until(page, "window.__atlas.map.getSize().x === window.innerWidth - 400", timeout=5000)


def test_mobile_layout(browser, base_url, artifacts):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=2)
    page = ctx.new_page()
    try:
        open_atlas(page, base_url)
        assert page.get_attribute("#sidebar-toggle", "aria-expanded") == "false"
        assert page.get_attribute("#app", "data-sidebar") == "closed"
        page.locator("#sidebar").wait_for(state="hidden", timeout=1000)
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        page.click("#sidebar-toggle")
        page.locator("#sidebar").wait_for(state="visible")
        page.click(".place[data-id='tabou']")
        page.locator("#detail").wait_for(state="visible")
        wait_map_settled(page)
        assert page.get_attribute("#app", "data-sidebar") == "closed"
        pin = page.locator(".leaflet-marker-icon[data-id='tabou']").bounding_box()
        sheet = page.locator("#detail").bounding_box()
        assert pin["y"] + pin["height"] <= sheet["y"], "the bottom sheet covers the selected marker"
        page.screenshot(path=str(artifacts / "mobile-detail.png"))
    finally:
        ctx.close()


@pytest.mark.network
def test_every_source_link_opens_in_the_browser(context):
    """Each source URL in the dataset loads in Chromium (429 = rate-limited but present)."""
    import json

    from app.config import DATA_DIR

    locations = json.loads((DATA_DIR / "locations.json").read_text(encoding="utf-8"))["locations"]
    urls = sorted({source["url"] for loc in locations for source in loc["sources"]})
    page = context.new_page()
    failures = []
    for url in urls:
        try:
            response = page.goto(url, wait_until="commit", timeout=30_000)
        except Exception as exc:  # DNS, TLS or timeout
            failures.append((url, str(exc).splitlines()[0]))
            continue
        if response is None or (response.status >= 400 and response.status != 429):
            failures.append((url, response.status if response else "no response"))
    page.close()
    assert not failures, failures
