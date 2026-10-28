// Small DOM and formatting helpers shared by the atlas modules.

export const $ = (selector, root = document) => root.querySelector(selector);

/**
 * Create an element: h('a', { href, class: 'x', onclick }, 'text', child).
 * Text is always inserted as text nodes, never parsed as HTML.
 */
export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'style') for (const [prop, v] of Object.entries(value)) node.style.setProperty(prop, v);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Inline SVG icon from a list of path definitions. */
export function icon(paths, size = 16) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('aria-hidden', 'true');
  for (const d of paths) {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

export const ICONS = {
  up: ['m6 15 6-6 6 6'],
  down: ['m6 9 6 6 6-6'],
  close: ['M6 6l12 12M18 6 6 18'],
  fit: ['M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5'],
};

export function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

/**
 * Normalise text for search: lower case, no diacritics, ligatures expanded,
 * punctuation collapsed. "Gît-le-Cœur" and "git le coeur" both become "git le coeur".
 */
export function normalizeText(value) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/œ/g, 'oe')
    .replace(/æ/g, 'ae')
    .replace(/ß/g, 'ss')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

export function formatDistance(metres) {
  if (metres < 950) return `${Math.round(metres / 10) * 10} m`;
  return `${(metres / 1000).toFixed(1)} km`;
}

export function formatDuration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')}`;
}

export function plural(n, word, pluralWord = `${word}s`) {
  return `${n} ${n === 1 ? word : pluralWord}`;
}

/** "9 rue Gît-le-Cœur, 75006 Paris, France" — used for Google Maps queries. */
export function mapsQuery(loc) {
  const { maps_query: query, street, postcode, city } = loc.address;
  return `${query ?? `${street}, ${postcode} ${city}`}, France`;
}

export function googleMapsSearchUrl(loc) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(mapsQuery(loc))}`;
}

/** Walking directions through every stop (origin, up to 9 waypoints, destination). */
export function googleMapsDirectionsUrl(stops) {
  const params = new URLSearchParams({ api: '1', travelmode: 'walking' });
  if (stops.length === 1) {
    params.set('destination', mapsQuery(stops[0]));
  } else {
    params.set('origin', mapsQuery(stops[0]));
    params.set('destination', mapsQuery(stops[stops.length - 1]));
    const waypoints = stops.slice(1, -1).map(mapsQuery);
    if (waypoints.length) params.set('waypoints', waypoints.join('|'));
  }
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

/** localStorage wrapper that never throws (private mode, blocked storage…). */
export const storage = {
  get(key, fallback = null) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: the preference simply isn't remembered */
    }
  },
};

export function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

export function isCompactLayout() {
  return window.matchMedia?.('(max-width: 760px)').matches ?? false;
}

export function announce(message) {
  const node = document.getElementById('announcer');
  if (!node) return;
  node.textContent = '';
  // A fresh text node in a new task makes screen readers announce repeats too.
  setTimeout(() => { node.textContent = message; }, 30);
}
