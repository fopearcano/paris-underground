// Walking itinerary: ordered stops, pedestrian routing via the backend, and an
// explicitly illustrative straight-line fallback when routing is unavailable.

import { $, ICONS, formatDistance, formatDuration, googleMapsDirectionsUrl, h, icon, plural, storage } from './utils.js';

const STORAGE_KEY = 'pu.route.v1';

export const EMPTY_ROUTE = Object.freeze({ stops: [], itineraryId: null, status: 'idle', result: null, message: '' });

export function restoredRoute(atlas) {
  const saved = storage.get(STORAGE_KEY);
  if (!saved || !Array.isArray(saved.stops)) return EMPTY_ROUTE;
  const stops = saved.stops.filter((id) => atlas.locationsById.has(id)).slice(0, atlas.routing.max_stops);
  const itineraryId = atlas.itineraries.some((i) => i.id === saved.itineraryId) ? saved.itineraryId : null;
  return { ...EMPTY_ROUTE, stops: [...new Set(stops)], itineraryId };
}

export function initRoute({ atlas, store, onSelect, onFit }) {
  const panel = $('#panel-route');
  let controller = null;
  let requested = '';

  function setRoute(patch) {
    const route = { ...store.get().route, ...patch };
    store.set({ route });
    storage.set(STORAGE_KEY, { stops: route.stops, itineraryId: route.itineraryId });
  }

  function setStops(stops, itineraryId = null) {
    setRoute({ stops, itineraryId, status: stops.length >= 2 ? 'loading' : 'idle', result: null, message: '' });
    compute(stops);
  }

  async function compute(stops) {
    controller?.abort();
    const key = stops.join(',');
    requested = key;
    if (stops.length < 2) return;
    if (!atlas.routing.enabled) {
      setRoute({ status: 'fallback', result: null, message: 'Pedestrian routing is disabled on this server.' });
      return;
    }
    controller = new AbortController();
    try {
      const response = await fetch(`/api/walking-route?stops=${encodeURIComponent(key)}`, { signal: controller.signal });
      const body = await response.json().catch(() => ({}));
      if (requested !== key) return;
      if (response.ok) setRoute({ status: 'routed', result: body, message: '' });
      else setRoute({ status: 'fallback', result: null, message: body.detail || `Routing failed (HTTP ${response.status}).` });
    } catch (error) {
      if (error.name === 'AbortError' || requested !== key) return;
      setRoute({ status: 'fallback', result: null, message: 'The routing service could not be reached.' });
    }
  }

  const api = {
    loadItinerary(id) {
      const itinerary = atlas.itineraries.find((i) => i.id === id);
      if (!itinerary) return;
      setStops([...itinerary.stops], itinerary.id);
      store.set({ tab: 'route', routeFitRequest: Date.now() });
    },
    toggleStop(id) {
      const { stops } = store.get().route;
      if (stops.includes(id)) setStops(stops.filter((s) => s !== id));
      else if (stops.length < atlas.routing.max_stops) setStops([...stops, id]);
    },
    move(id, delta) {
      const stops = [...store.get().route.stops];
      const from = stops.indexOf(id);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= stops.length) return;
      [stops[from], stops[to]] = [stops[to], stops[from]];
      setStops(stops);
    },
    clear() {
      controller?.abort();
      requested = '';
      setRoute({ ...EMPTY_ROUTE });
    },
    resume() {
      const { stops } = store.get().route;
      if (stops.length >= 2) setStops(stops, store.get().route.itineraryId);
    },
  };

  function stopTools(id, index, count) {
    const loc = atlas.locationsById.get(id);
    return h('span', { class: 'route-stop-tools' },
      h('button', { type: 'button', class: 'icon-button', 'aria-label': `Move ${loc.name} earlier`, disabled: index === 0, onclick: () => api.move(id, -1) }, icon(ICONS.up, 13)),
      h('button', { type: 'button', class: 'icon-button', 'aria-label': `Move ${loc.name} later`, disabled: index === count - 1, onclick: () => api.move(id, 1) }, icon(ICONS.down, 13)),
      h('button', { type: 'button', class: 'icon-button', 'aria-label': `Remove ${loc.name} from the route`, onclick: () => api.toggleStop(id) }, icon(ICONS.close, 13)));
  }

  function statusBox(route) {
    if (route.stops.length < 2) {
      return h('div', { class: 'route-status route-status--loading' }, 'Add at least one more stop to calculate a walking route.');
    }
    if (route.status === 'loading') {
      return h('div', { class: 'route-status route-status--loading', role: 'status' }, 'Calculating a pedestrian route…');
    }
    if (route.status === 'routed') {
      return h('div', { class: 'route-status route-status--routed', role: 'status' },
        h('div', {}, h('strong', {}, 'Pedestrian route'),
          'Calculated along OpenStreetMap streets and footpaths by the FOSSGIS OSRM foot profile. Times assume a steady walking pace; allow extra time at each stop.'));
    }
    return h('div', { class: 'route-status route-status--fallback', role: 'status', 'data-route-mode': 'illustrative' },
      h('div', {}, h('strong', {}, 'Illustrative route — not walking directions'),
        `${route.message} The stops are joined by straight dotted lines in walking order, so no walking distance is shown. Use Google Maps for turn-by-turn directions.`));
  }

  function render(state) {
    const { route } = state;
    if (!route.stops.length) {
      panel.replaceChildren(
        h('div', { class: 'route-head' },
          h('h2', {}, 'Walking route'),
          h('p', {}, 'Build a walk through underground Paris: load one of the suggested walks, or open any place and choose “Add to walking route”.')),
        h('div', { class: 'more-walks more-walks--start' },
          h('h3', {}, 'Suggested walks'),
          h('ul', {}, atlas.itineraries.map((it) => h('li', {},
            h('button', { type: 'button', 'data-itinerary': it.id, onclick: () => api.loadItinerary(it.id) },
              h('strong', {}, it.title), h('span', {}, `${plural(it.stops.length, 'stop')} · ${it.description}`)))))));
      return;
    }

    const itinerary = atlas.itineraries.find((i) => i.id === route.itineraryId);
    const routed = route.status === 'routed' && route.result;
    const stops = route.stops.map((id) => atlas.locationsById.get(id));

    const summary = h('dl', { class: 'route-summary' },
      h('div', {}, h('dt', {}, 'Stops'), h('dd', {}, stops.length)),
      routed ? h('div', {}, h('dt', {}, 'Walking distance'), h('dd', { id: 'route-distance' }, formatDistance(route.result.distance_m))) : null,
      routed ? h('div', {}, h('dt', {}, 'Walking time'), h('dd', {}, `≈ ${formatDuration(route.result.duration_s)}`)) : null);

    const list = h('ol', { class: 'route-stops' }, stops.map((loc, index) => {
      const leg = routed ? route.result.legs[index] : null;
      return h('li', { class: 'route-stop', 'data-id': loc.id },
        h('span', { class: 'route-stop-n', 'aria-hidden': 'true' }, index + 1),
        h('div', {},
          h('button', { type: 'button', class: 'route-stop-name', onclick: () => onSelect(loc.id, { source: 'route' }) }, loc.name),
          h('span', { class: 'route-stop-sub' }, `${loc.address.street} · ${loc.periodLabel}`),
          leg ? h('span', { class: 'route-leg' }, `↓ ${formatDistance(leg.distance_m)} · ${formatDuration(leg.duration_s)} to stop ${index + 2}`) : null),
        stopTools(loc.id, index, stops.length));
    }));

    const actions = h('div', { class: 'route-actions' },
      h('a', {
        class: 'primary',
        id: 'route-gmaps',
        href: googleMapsDirectionsUrl(stops),
        target: '_blank',
        rel: 'noopener noreferrer',
      }, stops.length > 1 ? 'Walking directions in Google Maps ↗' : 'Open in Google Maps ↗'),
      h('button', { type: 'button', onclick: onFit }, 'Fit route on map'),
      h('button', { type: 'button', id: 'route-clear', onclick: api.clear }, 'Clear route'));

    const others = atlas.itineraries.filter((it) => it.id !== route.itineraryId);
    const moreWalks = others.length
      ? h('div', { class: 'more-walks' },
          h('h3', {}, 'More walks'),
          h('ul', {}, others.map((it) => h('li', {},
            h('button', { type: 'button', 'data-itinerary': it.id, onclick: () => api.loadItinerary(it.id) },
              h('strong', {}, it.title), h('span', {}, plural(it.stops.length, 'stop')))))))
      : null;

    const note = h('p', { class: 'route-note' },
      routed
        ? [
            'Walking route: ',
            h('a', { href: route.result.attribution.provider_url, target: '_blank', rel: 'noopener noreferrer' }, 'FOSSGIS OSRM'),
            ' · Data © ',
            h('a', { href: 'https://www.openstreetmap.org/copyright', target: '_blank', rel: 'noopener noreferrer' }, 'OpenStreetMap contributors'),
            ' · ',
            h('a', { href: route.result.attribution.fix_the_map_url, target: '_blank', rel: 'noopener noreferrer' }, 'Fix the map'),
            '. ',
          ]
        : null,
      'Several stops are historical sites that no longer operate; see each place for its present-day status.');

    panel.replaceChildren(
      h('div', { class: 'route-head' },
        h('h2', {}, itinerary ? itinerary.title : 'Your walk'),
        h('p', {}, itinerary ? itinerary.description : `A custom walk of ${plural(stops.length, 'stop')}, in the order listed below.`)),
      summary,
      statusBox(route),
      list,
      actions,
      note,
      moreWalks);
  }

  return { ...api, render };
}

/** What the map should draw for the current route state. */
export function routeDrawing(route) {
  if (route.stops.length < 2) return null;
  if (route.status === 'routed' && route.result) return { kind: 'routed', geometry: route.result.geometry };
  if (route.status === 'fallback') return { kind: 'illustrative', stops: route.stops };
  return undefined; // still loading: keep whatever is drawn
}
