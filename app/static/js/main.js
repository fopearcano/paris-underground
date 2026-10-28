// Entry point: loads the atlas data and wires the modules together through one store.

import { createStore, loadAtlas, quarterCounts, visibleLocations } from './atlas.js';
import { initDetail } from './detail.js';
import { createAtlasMap } from './map.js';
import { initRoute, restoredRoute, routeDrawing } from './route.js';
import { initSidebar } from './sidebar.js';
import { initTimeline } from './timeline.js';
import { $, announce, h, isCompactLayout, storage } from './utils.js';

const BASEMAP_KEY = 'pu.basemap.v1';

const TILE_MESSAGES = {
  offline: ['You appear to be offline', 'The basemap needs a connection to {host}. Markers, the list, search, filters, the timeline and every historical record still work.'],
  error: ['Basemap tiles failed to load', 'Requests to {host} were blocked or failed (network filter, firewall or proxy). Markers and all historical data remain available.'],
  timeout: ['The basemap is taking too long', 'No map tiles have arrived from {host} yet. Markers and all historical data remain available while the map retries.'],
};

function fatal(title, detail) {
  $('#map-area').append(h('div', { class: 'app-error', role: 'alert' }, h('div', {}, h('strong', {}, title), detail)));
  $('#result-count').textContent = 'Unavailable';
}

async function boot() {
  let atlas;
  try {
    atlas = await loadAtlas();
  } catch (error) {
    fatal('The atlas could not be loaded', `${error.message} Check that the Paris Underground server is running, then reload the page.`);
    return;
  }

  const store = createStore({
    group: 'all',
    quarter: 'all',
    query: '',
    year: null,
    selectedId: null,
    basemap: storage.get(BASEMAP_KEY) === 'street' ? 'street' : 'night',
    tab: 'atlas',
    sidebarOpen: !isCompactLayout(),
    tiles: 'loading',
    route: restoredRoute(atlas),
    fitRequest: 0,
    routeFitRequest: 0,
  });

  // ---- Modules ----

  const sidebar = initSidebar({ atlas, store, onSelect: select, onSelectQuarter: selectQuarter, onToggleSidebar: toggleSidebar });
  const detail = initDetail({ atlas, onClose: () => select(null), onToggleRoute: (id) => route.toggleStop(id), onSelectQuarter: selectQuarter });
  const timeline = initTimeline({ atlas, store });
  const route = initRoute({ atlas, store, onSelect: select, onFit: fitRoute });

  const mapContainer = $('#map');
  const mapApi = createAtlasMap({
    container: mapContainer,
    atlas,
    onSelect: select,
    onSelectQuarter: selectQuarter,
    onTileStatus: (tiles) => store.set({ tiles }),
    getOverlays: overlayRects,
  });
  if (!mapApi) {
    store.set({ tiles: 'engine' });
  } else {
    new ResizeObserver(() => mapApi.invalidate()).observe(mapContainer);
  }

  /** Overlay rectangles relative to the map, so the map can avoid covering markers. */
  function overlayRects() {
    const base = mapContainer.getBoundingClientRect();
    const rel = (rect) => rect && { left: rect.left - base.left, right: rect.right - base.left, top: rect.top - base.top, bottom: rect.bottom - base.top };
    const topbar = $('.topbar').getBoundingClientRect();
    return { detail: rel(detail.rect()), timeline: rel(timeline.rect()), topbar: rel(topbar) };
  }

  // ---- Actions ----

  function select(id, { source = 'code' } = {}) {
    if (!id) {
      store.set({ selectedId: null });
      return;
    }
    const loc = atlas.locationsById.get(id);
    if (!loc) return;
    // A place opened from the route or a link may be hidden by filters: reveal it.
    if (!visibleLocations(atlas, store.get()).some((l) => l.id === id)) {
      store.set({ group: 'all', quarter: 'all', query: '', year: null });
    }
    store.set({ selectedId: id });
    announce(`${loc.name}, ${loc.periodLabel}. Details opened.`);
    if (isCompactLayout() && source !== 'map') toggleSidebar(false, { restoreFocus: false });
    mapApi?.focusLocation(id);
    sidebar.scrollToSelected(id);
    if (source === 'map') detail.focusTitle();
  }

  /** Filter to one quarter ('all' for the whole city) and show its then/today overview. */
  function selectQuarter(id) {
    if (id !== 'all' && !atlas.quartersById.has(id)) return;
    store.set({ quarter: id, tab: 'atlas', fitRequest: Date.now() });
    if (id === 'all') return;
    announce(`${atlas.quartersById.get(id).name}: then and today.`);
    if (!store.get().sidebarOpen) toggleSidebar(true, { focus: false });
    sidebar.revealOverview();
  }

  function toggleSidebar(open, { restoreFocus = true, focus = true } = {}) {
    store.set({ sidebarOpen: open });
    if (!isCompactLayout()) return;
    if (open && focus) $('#sidebar-close').focus();
    else if (restoreFocus) $('#sidebar-toggle').focus();
  }

  function fitRoute() {
    const { stops } = store.get().route;
    if (!mapApi || !stops.length) return;
    const latlngs = stops.map((id) => mapApi.markerFor(id).getLatLng());
    if (isCompactLayout()) toggleSidebar(false, { restoreFocus: false });
    mapApi.fitLatLngs(latlngs);
  }

  /** Shareable URL: #place=… for an open place, otherwise #quarter=… for a quarter. */
  function syncHash(state) {
    const target = state.selectedId ? `#place=${state.selectedId}` : state.quarter !== 'all' ? `#quarter=${state.quarter}` : '';
    if (window.location.hash === target) return;
    history.replaceState(null, '', target || window.location.pathname + window.location.search);
  }

  function parseHash() {
    const match = /^#(place|quarter)=([a-z0-9-]+)$/.exec(window.location.hash);
    if (!match) return {};
    const [, kind, id] = match;
    if (kind === 'place' && atlas.locationsById.has(id)) return { place: id };
    if (kind === 'quarter' && atlas.quartersById.has(id)) return { quarter: id };
    return {};
  }

  // ---- Static controls ----

  for (const button of document.querySelectorAll('.switcher [data-basemap]')) {
    button.addEventListener('click', () => store.set({ basemap: button.dataset.basemap }));
  }
  $('#route-cta').addEventListener('click', () => {
    route.loadItinerary(atlas.itineraries[0].id);
    if (!store.get().sidebarOpen) toggleSidebar(true);
  });
  $('#map-fallback-retry').addEventListener('click', () => mapApi?.retryTiles());
  let fallbackDismissed = false;
  $('#map-fallback-dismiss').addEventListener('click', () => {
    fallbackDismissed = true;
    $('#map-fallback').hidden = true;
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (store.get().selectedId) select(null);
    else if (isCompactLayout() && store.get().sidebarOpen) toggleSidebar(false);
  });
  // Crossing the phone breakpoint: docked sidebar on wide screens, closed drawer on phones.
  window.matchMedia('(max-width: 760px)').addEventListener('change', (event) => {
    store.set({ sidebarOpen: !event.matches });
  });
  window.addEventListener('hashchange', () => {
    const { place, quarter } = parseHash();
    if (place && place !== store.get().selectedId) select(place, { source: 'link' });
    else if (quarter && quarter !== store.get().quarter) selectQuarter(quarter);
  });

  // ---- Rendering ----

  function renderTiles(status) {
    const fallback = $('#map-fallback');
    const down = ['error', 'timeout', 'offline', 'engine'].includes(status);
    $('#map-area').classList.toggle('tiles-down', down);
    if (!down) {
      fallbackDismissed = false;
      fallback.hidden = true;
      return;
    }
    if (status === 'engine') {
      $('#map-fallback-title').textContent = 'The map engine could not be loaded';
      $('#map-fallback-text').textContent = 'Leaflet failed to load, so the interactive map is unavailable. Every location, its history and its sources remain available in the list.';
      $('#map-fallback-retry').hidden = true;
    } else {
      const host = new URL(atlas.map.tile_url.replace(/\{[a-z]\}/g, '0')).host;
      const [title, text] = TILE_MESSAGES[status];
      $('#map-fallback-title').textContent = title;
      $('#map-fallback-text').textContent = text.replace('{host}', host);
    }
    fallback.hidden = fallbackDismissed;
  }

  function render(state, changed) {
    const all = !changed;
    const has = (...keys) => all || keys.some((k) => changed.has(k));
    const visible = visibleLocations(atlas, state);
    const visibleIds = new Set(visible.map((loc) => loc.id));

    sidebar.render(state, changed, visible);
    if (has('selectedId', 'route')) detail.render(state);
    if (has('group', 'quarter', 'query', 'year')) timeline.render(state, visible);
    if (has('selectedId', 'quarter')) syncHash(state);
    if (has('route', 'tab')) route.render(state);
    if (has('tiles')) renderTiles(state.tiles);
    if (has('basemap')) {
      for (const button of document.querySelectorAll('.switcher [data-basemap]')) {
        button.setAttribute('aria-pressed', String(button.dataset.basemap === state.basemap));
      }
      storage.set(BASEMAP_KEY, state.basemap);
    }

    if (mapApi) renderMap(state, changed, has, visibleIds);

    if (state.selectedId && !visibleIds.has(state.selectedId)) {
      // A filter hid the selected place: close its panel once this render is complete.
      store.set({ selectedId: null });
    }
  }

  function renderMap(state, changed, has, visibleIds) {
    if (has('group', 'quarter', 'query', 'year', 'selectedId', 'route')) {
      mapApi.update({ visibleIds, selectedId: state.selectedId, year: state.year, routeStops: state.route.stops });
    }
    if (has('group', 'quarter', 'query', 'year')) mapApi.updateQuarters(state.quarter, quarterCounts(atlas, state));
    if (has('basemap')) mapApi.setBasemap(state.basemap);
    if (has('route')) {
      const drawing = routeDrawing(state.route);
      if (drawing !== undefined) mapApi.drawRoute(drawing);
    }
    if (changed?.has('fitRequest')) mapApi.fitVisible();
    if (changed?.has('routeFitRequest')) fitRoute();
  }

  // Read any #place= / #quarter= link before the first render rewrites the URL.
  const initial = parseHash();
  store.subscribe(render);
  render(store.get(), null);

  // ---- Initial view ----

  mapApi?.fitVisible({ animate: false });
  if (initial.place) select(initial.place, { source: 'link' });
  else if (initial.quarter) selectQuarter(initial.quarter);
  route.resume();

  // Test and debugging hook (read-only use).
  window.__atlas = {
    atlas,
    store,
    mapApi,
    get map() { return mapApi?.map ?? null; },
    visibleIds: () => [...(mapApi?.visibleIds ?? visibleLocations(atlas, store.get()).map((l) => l.id))],
  };
  document.documentElement.dataset.ready = 'true';
}

boot();
