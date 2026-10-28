"""The JSON historical database: schema, required content and internal consistency."""

from __future__ import annotations

import json
import math
import shutil

import pytest

from app.config import DATA_DIR, MAX_ROUTE_STOPS
from app.store import AtlasDataError, AtlasStore

# Location id -> filter group, as specified for the initial dataset.
EXPECTED_LOCATIONS = {
    "beat-hotel": "beat",
    "mistral": "beat",
    "moineau": "lettrist-situationist",
    "tonneau": "lettrist-situationist",
    "tabou": "jazz-existentialism",
    "club-sg": "jazz-existentialism",
    "caveau": "jazz-existentialism",
    "flore": "jazz-existentialism",
    "magots": "jazz-existentialism",
    "breton": "surrealism",
    "bateau": "montmartre-boheme",
    "chat-noir": "montmartre-boheme",
}

LEFT_BANK_WALK = ["tonneau", "mistral", "caveau", "beat-hotel", "tabou", "magots", "flore", "club-sg", "moineau"]


@pytest.fixture(scope="module")
def store() -> AtlasStore:
    return AtlasStore.load(DATA_DIR)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def test_the_twelve_original_locations_are_present(store):
    assert [loc.id for loc in store.locations] == list(EXPECTED_LOCATIONS)


@pytest.mark.parametrize("location_id,group", EXPECTED_LOCATIONS.items())
def test_location_movement_group(store, location_id, group):
    assert store.groups_for(store.location(location_id))[0] == group


def test_every_location_has_the_required_fields(store):
    for loc in store.locations:
        assert loc.name and loc.address.street and loc.address.arrondissement
        assert loc.periods and loc.figures and loc.sources
        assert len(loc.description) > 80 and loc.significance
        assert loc.status.summary


def test_prototype_coordinates_preserved_unless_documented_as_corrected(store):
    """Coordinates either match the prototype or record the prototype value they replace."""
    prototype = {
        "beat-hotel": (48.853847, 2.342753), "mistral": (48.85258, 2.34711), "tabou": (48.85472, 2.33944),
        "caveau": (48.85271, 2.34602), "flore": (48.85410, 2.33255), "magots": (48.85392, 2.33318),
        "bateau": (48.88611, 2.33750), "moineau": (48.85290, 2.33310), "tonneau": (48.84765, 2.34945),
        "club-sg": (48.85494, 2.33172), "breton": (48.88025, 2.33325), "chat-noir": (48.88020, 2.33770),
    }
    for loc in store.locations:
        current = (loc.coordinates.lat, loc.coordinates.lng)
        if current != prototype[loc.id]:
            assert loc.coordinates.prototype is not None, f"{loc.id} moved without recording the prototype pin"
            assert (loc.coordinates.prototype.lat, loc.coordinates.prototype.lng) == prototype[loc.id]
            assert loc.coordinates.note and "Corrected" in loc.coordinates.note


def test_coordinates_are_distinct_and_in_central_paris(store):
    for loc in store.locations:
        assert distance_m((loc.coordinates.lat, loc.coordinates.lng), (48.8566, 2.3522)) < 6000, loc.id
    points = [(loc.id, (loc.coordinates.lat, loc.coordinates.lng)) for loc in store.locations]
    for i, (a_id, a) in enumerate(points):
        for b_id, b in points[i + 1:]:
            assert distance_m(a, b) > 20, f"{a_id} and {b_id} share a pin"


def test_periods_fall_within_the_atlas_timeline(store):
    timeline = store.meta.timeline
    assert (timeline.start, timeline.end) == (1881, 1968)
    for loc in store.locations:
        for period in loc.periods:
            assert timeline.start <= period.start <= timeline.end, loc.id
            assert period.end is None or period.end <= timeline.end, loc.id


def test_sources_are_https_and_not_known_broken(store):
    for loc in store.locations:
        for source in loc.sources:
            assert source.url.scheme == "https"
            # This venue site serves an expired TLS certificate (checked 2026-10).
            assert "caveaudelahuchette.fr" not in str(source.url)


def test_left_bank_walk_has_the_suggested_stops(store):
    walk = next(i for i in store.itineraries if i.id == "left-bank")
    assert walk.stops == LEFT_BANK_WALK
    assert len(walk.stops) <= MAX_ROUTE_STOPS


def test_future_movement_groups_exist_but_are_empty(store):
    """The schema anticipates later expansion without inventing locations."""
    counts = {g["id"]: g["count"] for g in store.groups_payload()}
    for future in ("nineteenth-century", "lost-generation", "may-1968"):
        assert counts[future] == 0
    assert sum(1 for c in counts.values() if c) == 5


def test_a_location_can_have_several_movements_and_periods(store):
    tonneau = store.location("tonneau")
    assert tonneau.movements == ["lettrism", "situationism"]
    assert len(tonneau.periods) == 2


def test_ongoing_period_is_open_ended(store):
    assert store.location("caveau").periods[0].end is None
    assert store.timeline_bounds() == (1881, 1968)


def _broken_copy(tmp_path, mutate):
    data_dir = tmp_path / "data"
    shutil.copytree(DATA_DIR, data_dir)
    path = data_dir / "locations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data_dir


def test_unknown_movement_is_rejected(tmp_path):
    data_dir = _broken_copy(tmp_path, lambda d: d["locations"][0].update(movements=["vorticism"]))
    with pytest.raises(AtlasDataError, match="unknown movement 'vorticism'"):
        AtlasStore.load(data_dir)


def test_duplicate_ids_are_rejected(tmp_path):
    data_dir = _broken_copy(tmp_path, lambda d: d["locations"][1].update(id="beat-hotel"))
    with pytest.raises(AtlasDataError, match="duplicate location id 'beat-hotel'"):
        AtlasStore.load(data_dir)


def test_typos_in_field_names_are_rejected(tmp_path):
    data_dir = _broken_copy(tmp_path, lambda d: d["locations"][0].update(descripton="typo"))
    with pytest.raises(AtlasDataError, match="descripton"):
        AtlasStore.load(data_dir)


def test_coordinates_outside_paris_are_rejected(tmp_path):
    data_dir = _broken_copy(tmp_path, lambda d: d["locations"][0]["coordinates"].update(lat=2.34, lng=48.85))
    with pytest.raises(AtlasDataError, match="coordinates"):
        AtlasStore.load(data_dir)


def test_adding_a_location_is_just_json(tmp_path):
    """A new entry (here a real, documented address) needs no code changes."""
    def add(d):
        d["locations"].append({
            "id": "beach-odeon",
            "name": "Shakespeare and Company (Sylvia Beach)",
            "address": {"street": "12 rue de l'Odéon", "postcode": "75006", "arrondissement": "6e"},
            "coordinates": {"lat": 48.8505, "lng": 2.3389, "precision": "approximate"},
            "movements": ["lost-generation"],
            "periods": [{"start": 1921, "end": 1941, "label": "1921–1941", "certainty": "documented"}],
            "figures": [{"name": "Sylvia Beach", "role": "Bookseller, publisher"}],
            "description": "Sylvia Beach's bookshop and lending library, publisher of James Joyce's Ulysses in 1922.",
            "significance": "Test entry.",
            "status": {"category": "closed", "summary": "Closed in 1941."},
            "sources": [{"title": "Sylvia Beach", "publisher": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Sylvia_Beach", "kind": "encyclopedia"}],
        })
    store = AtlasStore.load(_broken_copy(tmp_path, add))
    assert len(store.locations) == 13
    assert {g["id"]: g["count"] for g in store.groups_payload()}["lost-generation"] == 1
