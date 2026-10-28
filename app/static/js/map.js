// Leaflet map: OSM basemap with tile-health monitoring, numbered pins, clustering and routes.

import { escapeHTML, icon, ICONS, prefersReducedMotion } from './utils.js';

// No tile loaded after this long: show the fallback notice.
const TILE_TIMEOUT_MS = 12000;
// This many consecutive tile errors: show the fallback notice.
const TILE_FAILURE_THRESHOLD = 4;
// Clustering stops at FOCUS_ZOOM, so a focused marker is always drawn on its own.
const FOCUS_ZOOM = 17;

/**
 * @returns {object|null} the map API, or null if Leaflet itself failed to load.
 */
export function createAtlasMap({ container, atlas, onSelect, onTileStatus, getOverlays }) {
  const L = window.L;
  if (!L) return null;
  const cfg = atlas.map;
  const reducedMotion = prefersReducedMotion();

  const map = L.map(container, {
    zoomControl: false,
    minZoom: cfg.min_zoom,
    maxZoom: cfg.tile_max_zoom,
    maxBounds: L.latLngBounds(cfg.bounds).pad(0.25),
    maxBoundsViscosity: 0.8,
    zoomSnap: 0.5,
  });
  map.setView(cfg.center, cfg.zoom, { animate: false });
  map.attributionControl.setPrefix(
    '<a href="https://leafletjs.com" target="_blank" rel="noopener noreferrer">Leaflet</a>',
  );
  L.control.zoom({ position: 'bottomright' }).addTo(map);

  // ---- Basemap -------------------------------------------------------------

  const tiles = L.tileLayer(cfg.tile_url, {
    maxZoom: cfg.tile_max_zoom,
    attribution: cfg.tile_attribution,
    // OSM's tile policy requires a Referer; send the page origin explicitly.
    referrerPolicy: 'strict-origin-when-cross-origin',
    className: 'pu-tiles',
    keepBuffer: 3,
    // Request tiles only where the map comes to rest, not for every zoom level a
    // fly-to animation passes through: far fewer requests to OSM's volunteer servers.
    updateWhenZooming: false,
    updateWhenIdle: true,
  });

  let tileStatus = 'loading';
  let tilesLoaded = 0;
  let consecutiveErrors = 0;
  let timeoutId = null;

  function setTileStatus(status) {
    if (status === tileStatus) return;
    tileStatus = status;
    onTileStatus?.(status);
  }
  function armTimeout() {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => {
      if (tilesLoaded === 0) setTileStatus(navigator.onLine === false ? 'offline' : 'timeout');
    }, TILE_TIMEOUT_MS);
  }
  tiles.on('tileload', () => {
    tilesLoaded += 1;
    consecutiveErrors = 0;
    setTileStatus('ok');
  });
  tiles.on('tileerror', () => {
    consecutiveErrors += 1;
    if (consecutiveErrors >= TILE_FAILURE_THRESHOLD) {
      setTileStatus(navigator.onLine === false ? 'offline' : 'error');
    }
  });
  window.addEventListener('offline', () => setTileStatus('offline'));
  window.addEventListener('online', () => retryTiles());

  function retryTiles() {
    consecutiveErrors = 0;
    tilesLoaded = 0;
    setTileStatus('loading');
    tiles.redraw();
    armTimeout();
  }

  tiles.addTo(map);
  armTimeout();

  // ---- Controls ------------------------------------------------------------

  const FitControl = L.Control.extend({
    options: { position: 'bottomright' },
    onAdd() {
      const wrap = L.DomUtil.create('div', 'leaflet-bar leaflet-control pu-fit');
      const link = L.DomUtil.create('a', '', wrap);
      link.href = '#';
      link.title = 'Fit map to visible locations';
      link.setAttribute('role', 'button');
      link.setAttribute('aria-label', 'Fit map to visible locations');
      link.append(icon(ICONS.fit, 17));
      L.DomEvent.disableClickPropagation(wrap);
      L.DomEvent.on(link, 'click', (event) => {
        L.DomEvent.preventDefault(event);
        api.fitVisible();
      });
      return wrap;
    },
  });
  new FitControl().addTo(map);

  // ---- Markers -------------------------------------------------------------

  const clustered = typeof L.markerClusterGroup === 'function';
  const markerLayer = clustered
    ? L.markerClusterGroup({
        maxClusterRadius: 40,
        disableClusteringAtZoom: FOCUS_ZOOM,
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        iconCreateFunction: (cluster) => {
          const n = cluster.getChildCount();
          return L.divIcon({
            className: 'pu-cluster',
            html: `<div>${n}<small aria-hidden="true">sites</small><span class="sr-only"> locations grouped here; activate to zoom in</span></div>`,
            iconSize: [40, 40],
          });
        },
      })
    : L.layerGroup();
  markerLayer.addTo(map);
  if (clustered) {
    markerLayer.on('clusterkeypress', (event) => {
      if (!isActivationKey(event.originalEvent)) return;
      L.DomEvent.preventDefault(event.originalEvent);
      event.layer.zoomToBounds({ padding: [60, 60] });
    });
  }

  const markers = new Map();
  for (const loc of atlas.locations) {
    const marker = L.marker([loc.coordinates.lat, loc.coordinates.lng], {
      icon: pinIcon(L, loc, {}),
      keyboard: true,
      riseOnHover: true,
    });
    marker._puKey = '';
    marker.bindTooltip(
      `<strong>${escapeHTML(loc.name)}</strong><span>${escapeHTML(loc.periodLabel)} · ${escapeHTML(loc.groupLabels[0])}</span>`,
      { direction: 'top', offset: [0, -17], className: 'pin-tooltip', opacity: 1 },
    );
    marker.on('click', () => onSelect(loc.id, { source: 'map' }));
    // Leaflet only handles Enter on markers with popups; pins here open the detail panel.
    marker.on('keypress', (event) => {
      if (!isActivationKey(event.originalEvent)) return;
      L.DomEvent.preventDefault(event.originalEvent);
      onSelect(loc.id, { source: 'map' });
    });
    marker.on('add', () => labelMarker(marker, loc));
    markers.set(loc.id, marker);
  }

  function labelMarker(marker, loc) {
    const el = marker.getElement();
    if (!el) return;
    el.dataset.id = loc.id;
    el.setAttribute('aria-label', `${loc.number}. ${loc.name} — ${loc.periodLabel}`);
  }

  // ---- Routes --------------------------------------------------------------

  const routeLayer = L.layerGroup().addTo(map);

  // ---- Helpers -------------------------------------------------------------

  /** Where the marker should land so the detail panel does not cover it. */
  function centreFor(latlng, zoom) {
    const overlays = getOverlays?.() ?? {};
    const panel = overlays.detail;
    if (!panel) return latlng;
    const size = map.getSize();
    const centre = size.divideBy(2);
    const margin = 36;
    const overlaps =
      centre.x > panel.left - margin && centre.x < panel.right + margin &&
      centre.y > panel.top - margin && centre.y < panel.bottom + margin;
    if (!overlaps) return latlng;
    const target = panel.right - panel.left > size.x * 0.7
      ? L.point(centre.x, Math.max(70, panel.top / 2 + 20)) // bottom sheet: use the space above it
      : L.point(Math.max(70, panel.left / 2), centre.y); // side panel: use the space to its left
    const projected = map.project(latlng, zoom).subtract(target.subtract(centre));
    return map.unproject(projected, zoom);
  }

  function fitPadding() {
    const overlays = getOverlays?.() ?? {};
    const size = map.getSize();
    let right = 50;
    let bottom = 50;
    if (overlays.timeline) bottom = Math.max(bottom, size.y - overlays.timeline.top + 24);
    if (overlays.detail) {
      if (overlays.detail.right - overlays.detail.left > size.x * 0.7) bottom = Math.max(bottom, size.y - overlays.detail.top + 24);
      else right = Math.max(right, size.x - overlays.detail.left + 24);
    }
    const top = (overlays.topbar?.bottom ?? 60) + 30;
    return { paddingTopLeft: [50, top], paddingBottomRight: [right, bottom] };
  }

  // ---- Public API ----------------------------------------------------------

  const api = {
    map,
    tiles,
    clustered,
    get tileStatus() { return tileStatus; },
    visibleIds: new Set(),

    /** Sync marker membership and appearance with the current state. */
    update({ visibleIds, selectedId, year, routeStops }) {
      api.visibleIds = visibleIds;
      const toAdd = [];
      const toRemove = [];
      for (const [id, marker] of markers) {
        const want = visibleIds.has(id);
        const has = markerLayer.hasLayer(marker);
        if (want && !has) toAdd.push(marker);
        else if (!want && has) toRemove.push(marker);
      }
      if (clustered) {
        if (toRemove.length) markerLayer.removeLayers(toRemove);
        if (toAdd.length) markerLayer.addLayers(toAdd);
      } else {
        toRemove.forEach((m) => markerLayer.removeLayer(m));
        toAdd.forEach((m) => markerLayer.addLayer(m));
      }
      for (const loc of atlas.locations) {
        const marker = markers.get(loc.id);
        const opts = {
          selected: loc.id === selectedId,
          inPeriod: year !== null && visibleIds.has(loc.id),
          routeIndex: routeStops.indexOf(loc.id),
        };
        const key = `${opts.selected}|${opts.inPeriod}|${opts.routeIndex}`;
        if (key !== marker._puKey) {
          marker._puKey = key;
          marker.setIcon(pinIcon(L, loc, opts));
          marker.setZIndexOffset(opts.selected ? 1000 : 0);
          labelMarker(marker, loc);
        }
      }
    },

    focusLocation(id, { animate = true } = {}) {
      const marker = markers.get(id);
      if (!marker) return;
      const zoom = Math.max(map.getZoom(), FOCUS_ZOOM);
      const target = centreFor(marker.getLatLng(), zoom);
      const animated = animate && !reducedMotion;
      if (animated) map.flyTo(target, zoom, { duration: 0.8 });
      else map.setView(target, zoom, { animate: false });
    },

    fitVisible({ animate = true } = {}) {
      const points = [...api.visibleIds].map((id) => markers.get(id).getLatLng());
      if (!points.length) return;
      const animated = animate && !reducedMotion;
      if (points.length === 1) {
        map.setView(centreFor(points[0], FOCUS_ZOOM), FOCUS_ZOOM, { animate: animated });
        return;
      }
      map.fitBounds(L.latLngBounds(points), { ...fitPadding(), maxZoom: FOCUS_ZOOM, animate: animated });
    },

    fitLatLngs(latlngs, { animate = true } = {}) {
      if (!latlngs.length) return;
      map.fitBounds(L.latLngBounds(latlngs), { ...fitPadding(), maxZoom: FOCUS_ZOOM, animate: animate && !reducedMotion });
    },

    setBasemap(mode) {
      container.classList.toggle('is-night', mode === 'night');
      container.classList.toggle('is-street', mode === 'street');
    },

    /** route: null, {kind: 'routed', geometry} or {kind: 'illustrative', stops: [ids]} */
    drawRoute(route) {
      routeLayer.clearLayers();
      if (!route) return [];
      if (route.kind === 'routed') {
        const latlngs = route.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
        L.polyline(latlngs, { color: '#0B0D0E', weight: 8, opacity: 0.7, interactive: false, className: 'route-line route-line--casing' }).addTo(routeLayer);
        L.polyline(latlngs, { color: '#F2D35B', weight: 4, opacity: 0.95, interactive: false, className: 'route-line route-line--routed' }).addTo(routeLayer);
        return latlngs;
      }
      const latlngs = route.stops.map((id) => markers.get(id).getLatLng());
      L.polyline(latlngs, {
        color: '#F2D35B', weight: 3, opacity: 0.9, dashArray: '2 9', lineCap: 'round',
        interactive: false, className: 'route-line route-line--illustrative',
      }).addTo(routeLayer);
      return latlngs;
    },

    retryTiles,
    invalidate: () => map.invalidateSize({ pan: false }),
    markerFor: (id) => markers.get(id),
  };
  return api;
}

function isActivationKey(event) {
  return event?.key === 'Enter' || event?.key === ' ';
}

function pinIcon(L, loc, { selected = false, inPeriod = false, routeIndex = -1 }) {
  const classes = ['pu-pin'];
  if (selected) classes.push('is-selected');
  if (inPeriod) classes.push('in-period');
  const badge = routeIndex >= 0 ? `<span class="pin-route" title="Walking route stop ${routeIndex + 1}">${routeIndex + 1}</span>` : '';
  return L.divIcon({
    className: classes.join(' '),
    html: `<span class="pin-outer" style="--c:${loc.color};--c-soft:${loc.color}44"><span class="pin-inner">${loc.number}</span>${badge}</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
    tooltipAnchor: [0, 0],
  });
}
