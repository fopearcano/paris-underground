// Atlas data: loading, indexing and the filter logic shared by the list, map and timeline.

import { normalizeText } from './utils.js';

export const STATUS_LABELS = {
  operating: 'Still operating',
  closed: 'Closed',
  demolished: 'Demolished',
  repurposed: 'Repurposed',
  rebuilt: 'Rebuilt',
  private: 'Private building',
  public: 'Public space',
  unknown: 'Current use unverified',
};

export const PRECISION_LABELS = {
  address: 'Marker placed at the street address',
  building: 'Marker placed on the building',
  street: 'Marker placed on the street; exact building uncertain',
  approximate: 'Approximate location',
};

export async function loadAtlas(fetchImpl = window.fetch.bind(window)) {
  const response = await fetchImpl('/api/atlas', { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`The atlas data could not be loaded (HTTP ${response.status}).`);
  return prepareAtlas(await response.json());
}

/** Index the API payload and precompute search text, colours and labels. */
export function prepareAtlas(data) {
  const groups = new Map(data.groups.map((g) => [g.id, g]));
  const movements = new Map(data.movements.map((m) => [m.id, m]));
  const quarters = new Map(data.quarters.map((q) => [q.id, q]));
  const timeline = data.timeline;

  const locations = data.locations.map((loc) => {
    const primary = groups.get(loc.groups[0]);
    const movementLabels = loc.movements.map((id) => movements.get(id)?.label ?? id);
    const groupLabels = loc.groups.map((id) => groups.get(id)?.label ?? id);
    const quarter = quarters.get(loc.quarter);
    // Leading space so query tokens can be matched at the start of words.
    const searchText = ' ' + normalizeText([
      loc.name,
      loc.address.street,
      loc.address.arrondissement,
      `${parseInt(loc.address.arrondissement, 10) || ''} arrondissement`,
      loc.address.historical_note,
      quarter?.name,
      ...movementLabels,
      ...groupLabels,
      ...loc.figures.flatMap((f) => [f.name, f.role]),
      ...loc.periods.map((p) => p.label),
      ...loc.tags,
      loc.then,
      loc.description,
      loc.significance,
      loc.status.summary,
    ].join(' '));
    return {
      ...loc,
      color: primary?.color ?? '#F2D35B',
      primaryGroup: primary,
      movementLabels,
      groupLabels,
      quarterInfo: quarter,
      periodLabel: loc.periods.map((p) => p.label).join(' · '),
      searchText,
    };
  });

  return {
    ...data,
    groupsById: groups,
    quartersById: quarters,
    locations,
    locationsById: new Map(locations.map((loc) => [loc.id, loc])),
    // Groups with no locations yet (future expansion) stay out of the filter bar.
    activeGroups: data.groups.filter((g) => g.count > 0),
    activeQuarters: data.quarters.filter((q) => q.count > 0),
    timeline,
  };
}

export function queryTokens(query) {
  const normalized = normalizeText(query);
  return normalized ? normalized.split(' ') : [];
}

export function matchesGroup(loc, group) {
  return group === 'all' || loc.groups.includes(group);
}

export function matchesQuarter(loc, quarter) {
  return quarter === 'all' || loc.quarter === quarter;
}

/** Every query token must begin some word of the location's searchable text. */
export function matchesQuery(loc, tokens) {
  return tokens.every((token) => loc.searchText.includes(` ${token}`));
}

export function activeInYear(loc, year, timelineEnd) {
  if (year === null || year === undefined) return true;
  return loc.periods.some((p) => year >= p.start && year <= (p.end ?? timelineEnd));
}

/** Predicate for every active filter; `except` leaves one out (for faceted counts). */
function filterFor(atlas, state, except = null) {
  const tokens = queryTokens(state.query);
  return (loc) =>
    (except === 'group' || matchesGroup(loc, state.group)) &&
    (except === 'quarter' || matchesQuarter(loc, state.quarter)) &&
    matchesQuery(loc, tokens) &&
    activeInYear(loc, state.year, atlas.timeline.end);
}

/** Every filter combined: movement group, quarter, search query and timeline year. */
export function visibleLocations(atlas, state) {
  return atlas.locations.filter(filterFor(atlas, state));
}

/** Per-group counts under the other filters (for the movement pills). */
export function groupCounts(atlas, state) {
  const pool = atlas.locations.filter(filterFor(atlas, state, 'group'));
  const counts = { all: pool.length };
  for (const group of atlas.activeGroups) counts[group.id] = pool.filter((loc) => loc.groups.includes(group.id)).length;
  return counts;
}

/** Per-quarter counts under the other filters (for the quarter cards and map labels). */
export function quarterCounts(atlas, state) {
  const pool = atlas.locations.filter(filterFor(atlas, state, 'quarter'));
  const counts = { all: pool.length };
  for (const quarter of atlas.activeQuarters) counts[quarter.id] = pool.filter((loc) => loc.quarter === quarter.id).length;
  return counts;
}

export function hasActiveFilters(state) {
  return state.group !== 'all' || state.quarter !== 'all' || state.query.trim() !== '' || state.year !== null;
}

/** Minimal observable store: set() merges a patch and notifies with the changed keys. */
export function createStore(initial) {
  let state = initial;
  const listeners = new Set();
  return {
    get: () => state,
    set(patch) {
      const previous = state;
      state = { ...state, ...patch };
      const changed = Object.keys(patch).filter((key) => previous[key] !== state[key]);
      if (changed.length) for (const fn of listeners) fn(state, new Set(changed), previous);
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
