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

# Places added for the districts (quarter id -> location ids).
NEW_BY_QUARTER = {
    "montmartre-pigalle": ["mirliton", "lapin-agile", "moulin-rouge", "nouvelle-athenes", "grand-duc", "musee-montmartre"],
    "latin-quarter": ["sylvia-beach", "joyce", "hemingway", "orwell", "sorbonne-1968", "gay-lussac-1968", "odeon-1968"],
    "belleville": ["piaf-belleville", "rue-vilin", "ronis-belvedere"],
    "menilmontant": ["bellevilloise", "chevalier", "pere-lachaise"],
    "denfert-rochereau": ["catacombs", "liberation-post"],
}


@pytest.fixture(scope="module")
def store() -> AtlasStore:
    return AtlasStore.load(DATA_DIR)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def test_the_twelve_original_locations_come_first(store):
    assert [loc.id for loc in store.locations[:12]] == list(EXPECTED_LOCATIONS)


def test_district_places_are_present(store):
    for quarter, ids in NEW_BY_QUARTER.items():
        for location_id in ids:
            loc = store.location(location_id)
            assert loc is not None, location_id
            assert loc.quarter == quarter, location_id
    assert len(store.locations) == 12 + sum(len(ids) for ids in NEW_BY_QUARTER.values())


def test_every_quarter_has_a_then_and_now_overview(store):
    assert [q.id for q in store.quarters] == [
        "montmartre-pigalle", "latin-quarter", "saint-germain", "belleville", "menilmontant", "denfert-rochereau"]
    counts = {q["id"]: q["count"] for q in store.quarters_payload()}
    assert all(counts.values()), counts
    for quarter in store.quarters:
        assert len(quarter.then) > 200 and len(quarter.now) > 150, quarter.id
        assert all(src.url.scheme == "https" for src in quarter.sources)


def test_every_location_compares_then_and_today(store):
    for loc in store.locations:
        assert loc.then and loc.status.summary, loc.id
        assert loc.then != loc.status.summary, loc.id


@pytest.mark.parametrize("location_id,group", EXPECTED_LOCATIONS.items())
def test_location_movement_group(store, location_id, group):
    assert store.groups_for(store.location(location_id))[0] == group


def test_every_location_has_the_required_fields(store):
    for loc in store.locations:
        assert loc.name and loc.address.street and loc.address.arrondissement
        assert loc.periods and loc.sources  # a street or an ossuary may have no named figures
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
    for loc in store.locations[:12]:
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


def test_every_location_overlaps_the_atlas_timeline(store):
    """Periods may start before 1881 or run past 1968, but each place shows up on the slider."""
    timeline = store.meta.timeline
    assert (timeline.start, timeline.end) == (1881, 1968)
    for loc in store.locations:
        assert any(p.start <= timeline.end and (p.end is None or p.end >= timeline.start) for p in loc.periods), loc.id
    assert store.timeline_bounds() == (1881, 1968)


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
    assert counts["nineteenth-century"] == 0
    assert [gid for gid, n in counts.items() if n] == [
        "beat", "jazz-existentialism", "lettrist-situationist", "surrealism", "montmartre-boheme",
        "popular-paris", "lost-generation", "subterranean", "may-1968"]


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


def test_unknown_quarter_is_rejected(tmp_path):
    data_dir = _broken_copy(tmp_path, lambda d: d["locations"][0].update(quarter="marais"))
    with pytest.raises(AtlasDataError, match="unknown quarter 'marais'"):
        AtlasStore.load(data_dir)


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
    """A new entry needs no code changes; one entirely before 1881 widens the timeline."""
    def add(d):
        d["locations"].append({
            "id": "hotel-lauzun",
            "name": "Hôtel de Lauzun (Baudelaire)",
            "quarter": "latin-quarter",
            "address": {"street": "17 quai d'Anjou", "postcode": "75004", "arrondissement": "4e"},
            "coordinates": {"lat": 48.8516, "lng": 2.3577, "precision": "approximate"},
            "movements": ["symbolism"],
            "periods": [{"start": 1843, "end": 1845, "label": "1843–1845", "certainty": "documented"}],
            "figures": [{"name": "Charles Baudelaire", "role": "Poet"}],
            "then": "Baudelaire's rooms in the Hôtel Pimodan, home of the Club des Hashischins.",
            "description": "Test entry: Charles Baudelaire lived in this hôtel particulier on the Île Saint-Louis in the 1840s.",
            "significance": "Test entry.",
            "status": {"category": "private", "summary": "Private hôtel particulier."},
            "sources": [{"title": "Hôtel de Lauzun", "publisher": "Wikipedia", "url": "https://en.wikipedia.org/wiki/H%C3%B4tel_de_Lauzun", "kind": "encyclopedia"}],
        })
    store = AtlasStore.load(_broken_copy(tmp_path, add))
    assert store.location("hotel-lauzun") is not None
    assert {g["id"]: g["count"] for g in store.groups_payload()}["nineteenth-century"] == 1
    assert store.timeline_bounds() == (1843, 1968)
