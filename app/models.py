"""Schema for the atlas JSON files in app/data.

Models forbid unknown keys, so a typo in a JSON file fails loudly at startup
instead of silently dropping data.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)]
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
Year = Annotated[int, Field(ge=1700, le=2100)]

# How precisely a marker matches the historical site.
Precision = Literal["address", "building", "street", "approximate"]
# Whether a date range is documented by sources or reconstructed from them.
Certainty = Literal["documented", "approximate"]
# Present-day status of the site, kept separate from its historical period.
StatusCategory = Literal[
    "operating", "closed", "demolished", "repurposed", "rebuilt", "private", "public", "unknown"
]
SourceKind = Literal["museum", "institution", "archive", "encyclopedia", "venue", "press", "book"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LatLng(Strict):
    lat: float
    lng: float


class Coordinates(Strict):
    # Bounds of greater Paris: catches swapped or mistyped coordinates.
    lat: float = Field(ge=48.75, le=48.95)
    lng: float = Field(ge=2.15, le=2.55)
    precision: Precision
    note: str | None = None
    # The prototype's original pin, kept when a coordinate was corrected.
    prototype: LatLng | None = None


class Address(Strict):
    street: str
    postcode: str = Field(pattern=r"^75\d{3}$")
    arrondissement: str
    city: str = "Paris"
    historical_note: str | None = None
    # Search text for Google Maps when `street` is not a plain postal address.
    maps_query: str | None = None

    @property
    def full(self) -> str:
        return f"{self.street}, {self.postcode} {self.city}"


class Period(Strict):
    start: Year
    end: Year | None = None  # None: still significant / ongoing
    label: str
    certainty: Certainty
    note: str | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.end is not None and self.end < self.start:
            raise ValueError(f"period ends ({self.end}) before it starts ({self.start})")
        return self


class Figure(Strict):
    name: str
    role: str


class Status(Strict):
    category: StatusCategory
    summary: str


class Source(Strict):
    title: str
    publisher: str
    url: HttpUrl
    kind: SourceKind

    @field_validator("url")
    @classmethod
    def _https(cls, url: HttpUrl) -> HttpUrl:
        if url.scheme != "https":
            raise ValueError("source URLs must use https")
        return url


class Location(Strict):
    id: Slug
    name: str
    quarter: Slug
    address: Address
    coordinates: Coordinates
    movements: list[Slug] = Field(min_length=1)
    periods: list[Period] = Field(min_length=1)
    figures: list[Figure] = Field(default_factory=list)
    # One-line summary of the place in its period, shown opposite `status` ("today").
    then: str = Field(min_length=20, max_length=160)
    description: str = Field(min_length=40)
    significance: str
    caveats: list[str] = Field(default_factory=list)
    status: Status
    sources: list[Source] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class Quarter(Strict):
    """A historic district, with a then-and-now overview."""

    id: Slug
    name: str
    arrondissements: str
    label_position: tuple[float, float]
    then: str = Field(min_length=80)
    now: str = Field(min_length=80)
    sources: list[Source] = Field(min_length=1)


class Group(Strict):
    id: Slug
    label: str
    short_label: str
    color: HexColor
    order: int
    description: str


class Movement(Strict):
    id: Slug
    label: str
    group: Slug


class Itinerary(Strict):
    id: Slug
    title: str
    description: str
    stops: list[Slug] = Field(min_length=2)


class Timeline(Strict):
    start: Year
    end: Year
    ticks: list[Year]
    note: str


class MapView(Strict):
    center: tuple[float, float]
    zoom: int = Field(ge=1, le=19)
    min_zoom: int = Field(ge=1, le=19)
    bounds: tuple[tuple[float, float], tuple[float, float]]


class FieldNotes(Strict):
    label: str
    title: str


class AtlasMeta(Strict):
    schema_version: Literal[1]
    title: str
    subtitle: str
    kicker: str
    field_notes: FieldNotes
    timeline: Timeline
    map: MapView
    last_reviewed: str


class LocationsFile(Strict):
    schema_version: Literal[1]
    locations: list[Location]


class MovementsFile(Strict):
    schema_version: Literal[1]
    groups: list[Group]
    movements: list[Movement]


class QuartersFile(Strict):
    schema_version: Literal[1]
    quarters: list[Quarter]


class ItinerariesFile(Strict):
    schema_version: Literal[1]
    itineraries: list[Itinerary]
