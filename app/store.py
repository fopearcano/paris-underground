"""Loads, validates and cross-checks the atlas data files."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from .config import MAX_ROUTE_STOPS
from .models import (
    AtlasMeta,
    Group,
    ItinerariesFile,
    Itinerary,
    Location,
    LocationsFile,
    Movement,
    MovementsFile,
    Quarter,
    QuartersFile,
)


class AtlasDataError(RuntimeError):
    """Raised when a data file is missing, malformed or inconsistent."""


def _read(path: Path, model: type[BaseModel]) -> Any:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AtlasDataError(f"Missing data file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AtlasDataError(f"{path.name} is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise AtlasDataError(f"{path.name} failed validation:\n{exc}") from exc


def _duplicates(ids: list[str]) -> list[str]:
    return sorted(i for i, n in Counter(ids).items() if n > 1)


@dataclass(frozen=True)
class AtlasStore:
    meta: AtlasMeta
    groups: list[Group]
    movements: list[Movement]
    locations: list[Location]
    itineraries: list[Itinerary]
    quarters: list[Quarter]

    @classmethod
    def load(cls, data_dir: Path) -> "AtlasStore":
        meta = _read(data_dir / "atlas.json", AtlasMeta)
        movements_file = _read(data_dir / "movements.json", MovementsFile)
        locations_file = _read(data_dir / "locations.json", LocationsFile)
        itineraries_file = _read(data_dir / "itineraries.json", ItinerariesFile)
        quarters_file = _read(data_dir / "quarters.json", QuartersFile)
        store = cls(
            meta=meta,
            groups=sorted(movements_file.groups, key=lambda g: g.order),
            movements=list(movements_file.movements),
            locations=list(locations_file.locations),
            itineraries=list(itineraries_file.itineraries),
            quarters=list(quarters_file.quarters),
        )
        store._check_references()
        return store

    def _check_references(self) -> None:
        problems: list[str] = []
        for kind, items in (
            ("group", self.groups),
            ("movement", self.movements),
            ("location", self.locations),
            ("itinerary", self.itineraries),
            ("quarter", self.quarters),
        ):
            for dup in _duplicates([item.id for item in items]):
                problems.append(f"duplicate {kind} id '{dup}'")

        group_ids = {g.id for g in self.groups}
        movement_ids = {m.id for m in self.movements}
        location_ids = {loc.id for loc in self.locations}
        quarter_ids = {q.id for q in self.quarters}

        for movement in self.movements:
            if movement.group not in group_ids:
                problems.append(f"movement '{movement.id}' refers to unknown group '{movement.group}'")
        for loc in self.locations:
            for mid in loc.movements:
                if mid not in movement_ids:
                    problems.append(f"location '{loc.id}' refers to unknown movement '{mid}'")
            if loc.quarter not in quarter_ids:
                problems.append(f"location '{loc.id}' refers to unknown quarter '{loc.quarter}'")
        for itinerary in self.itineraries:
            for stop in itinerary.stops:
                if stop not in location_ids:
                    problems.append(f"itinerary '{itinerary.id}' refers to unknown location '{stop}'")
            if len(itinerary.stops) > MAX_ROUTE_STOPS:
                problems.append(f"itinerary '{itinerary.id}' has more than {MAX_ROUTE_STOPS} stops")
            for dup in _duplicates(itinerary.stops):
                problems.append(f"itinerary '{itinerary.id}' repeats stop '{dup}'")

        timeline = self.meta.timeline
        if timeline.end <= timeline.start:
            problems.append("timeline end must be after its start")

        if problems:
            raise AtlasDataError("Inconsistent atlas data:\n  - " + "\n  - ".join(problems))

    # Lookups -----------------------------------------------------------------

    def location(self, location_id: str) -> Location | None:
        return next((loc for loc in self.locations if loc.id == location_id), None)

    def groups_for(self, loc: Location) -> list[str]:
        """Filter groups of a location, primary (first movement's) group first."""
        by_movement = {m.id: m.group for m in self.movements}
        groups: list[str] = []
        for mid in loc.movements:
            if by_movement[mid] not in groups:
                groups.append(by_movement[mid])
        return groups

    # Serialisation -----------------------------------------------------------

    def location_payload(self, loc: Location, number: int) -> dict[str, Any]:
        data = loc.model_dump(mode="json")
        data["number"] = number
        data["groups"] = self.groups_for(loc)
        data["address"]["full"] = loc.address.full
        return data

    def locations_payload(self) -> list[dict[str, Any]]:
        return [self.location_payload(loc, i) for i, loc in enumerate(self.locations, start=1)]

    def groups_payload(self) -> list[dict[str, Any]]:
        counts = {g.id: 0 for g in self.groups}
        for loc in self.locations:
            for gid in self.groups_for(loc):
                counts[gid] += 1
        return [{**g.model_dump(mode="json"), "count": counts[g.id]} for g in self.groups]

    def quarters_payload(self) -> list[dict[str, Any]]:
        counts = Counter(loc.quarter for loc in self.locations)
        return [{**q.model_dump(mode="json"), "count": counts[q.id]} for q in self.quarters]

    def timeline_bounds(self) -> tuple[int, int]:
        """The configured timeline, widened only for locations it would otherwise miss.

        A period that overlaps the timeline (say 1874–1890, or 1960–1979) is simply
        clipped on the slider; only a location with no period inside the range at
        all (a future Baudelaire entry, for instance) widens the timeline.
        """
        lo, hi = self.meta.timeline.start, self.meta.timeline.end
        start, end = lo, hi
        for loc in self.locations:
            if any(p.start <= hi and (p.end is None or p.end >= lo) for p in loc.periods):
                continue
            for p in loc.periods:
                start = min(start, p.start)
                end = max(end, p.start if p.end is None else p.end)
        return start, end
