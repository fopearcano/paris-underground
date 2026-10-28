// Sidebar: search, movement filters, location list, tabs and the collapsible drawer.

import { STATUS_LABELS, groupCounts, hasActiveFilters } from './atlas.js';
import { $, h, plural } from './utils.js';

export function initSidebar({ atlas, store, onSelect, onToggleSidebar }) {
  const search = $('#search');
  const filters = $('#filters');
  const list = $('#place-list');
  const resultCount = $('#result-count');
  const clearButton = $('#clear-filters');
  const tabs = [$('#tab-atlas'), $('#tab-route')];

  $('#metric-locations').textContent = atlas.locations.length;
  $('#metric-movements').textContent = atlas.activeGroups.length;

  // ---- Search ----
  search.addEventListener('input', () => store.set({ query: search.value }));
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && search.value) {
      event.stopPropagation();
      search.value = '';
      store.set({ query: '' });
    }
  });
  document.addEventListener('keydown', (event) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName ?? '');
    if (event.key === '/' && !typing && !event.metaKey && !event.ctrlKey) {
      event.preventDefault();
      if (store.get().sidebarOpen === false) onToggleSidebar(true);
      search.focus();
    }
  });

  // ---- Movement filters ----
  const pills = [
    { id: 'all', label: 'All', color: null },
    ...atlas.activeGroups.map((g) => ({ id: g.id, label: g.label, color: g.color })),
  ].map((item) =>
    h('button', {
      type: 'button',
      class: 'pill',
      'data-group': item.id,
      'aria-pressed': 'false',
      onclick: () => store.set({ group: item.id, fitRequest: Date.now() }),
    },
    item.color ? h('span', { class: 'pill-dot', style: { '--c': item.color }, 'aria-hidden': 'true' }) : null,
    h('span', { class: 'pill-label' }, item.label),
    h('span', { class: 'pill-count' })),
  );
  filters.replaceChildren(...pills);

  clearButton.addEventListener('click', () => {
    search.value = '';
    store.set({ group: 'all', query: '', year: null, fitRequest: Date.now() });
  });

  // ---- Tabs (WAI-ARIA tabs pattern) ----
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => store.set({ tab: index === 0 ? 'atlas' : 'route' }));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus();
      store.set({ tab: next === 0 ? 'atlas' : 'route' });
    });
  });

  // ---- Drawer / collapse ----
  $('#sidebar-toggle').addEventListener('click', () => onToggleSidebar(!store.get().sidebarOpen));
  $('#sidebar-close').addEventListener('click', () => onToggleSidebar(false));
  $('#scrim').addEventListener('click', () => onToggleSidebar(false));

  function renderFilters(state) {
    const counts = groupCounts(atlas, state);
    for (const pill of pills) {
      const id = pill.dataset.group;
      const n = counts[id] ?? 0;
      pill.setAttribute('aria-pressed', String(state.group === id));
      pill.classList.toggle('is-empty', n === 0);
      pill.querySelector('.pill-count').textContent = n;
      pill.setAttribute('aria-label', `${pill.querySelector('.pill-label').textContent}: ${plural(n, 'location')}`);
    }
    if (search.value !== state.query) search.value = state.query;
    clearButton.disabled = !hasActiveFilters(state);
  }

  function renderList(state, visible) {
    const total = atlas.locations.length;
    resultCount.textContent = visible.length === total
      ? plural(total, 'location')
      : `${visible.length} of ${plural(total, 'location')}`;
    $('#tab-atlas-count').textContent = visible.length;

    if (!visible.length) {
      list.replaceChildren(h('li', { class: 'empty' },
        'No matching places.', h('br'), 'Try another movement, year or search.', h('br'),
        h('button', { type: 'button', class: 'text-button', onclick: () => clearButton.click() }, 'Clear filters ↺')));
      return;
    }
    list.replaceChildren(...visible.map((loc) => {
      const selected = loc.id === state.selectedId;
      const inRoute = state.route.stops.includes(loc.id);
      return h('li', {},
        h('button', {
          type: 'button',
          class: 'place',
          'data-id': loc.id,
          'aria-current': selected ? 'true' : 'false',
          onclick: () => onSelect(loc.id, { source: 'list' }),
        },
        h('span', { class: 'number' }, String(loc.number).padStart(2, '0')),
        h('span', { class: 'place-text' },
          h('span', { class: 'place-title' }, loc.name),
          h('span', { class: 'place-sub' }, `${loc.address.street} · ${loc.address.arrondissement}`),
          h('span', { class: 'place-meta' },
            h('span', { class: 'era', title: 'Period of historical significance' }, loc.periodLabel),
            h('span', { class: `status status--${loc.status.category}`, title: `Today: ${loc.status.summary}` },
              h('span', { class: 'sr-only' }, 'Today: '), STATUS_LABELS[loc.status.category]),
            inRoute ? h('span', { class: 'place-flag' }, `Route stop ${state.route.stops.indexOf(loc.id) + 1}`) : null)),
        h('span', { class: 'dot', style: { '--c': loc.color }, title: loc.groupLabels.join(', '), 'aria-hidden': 'true' })));
    }));
  }

  function renderTabs(state) {
    const routeTab = state.tab === 'route';
    tabs[0].setAttribute('aria-selected', String(!routeTab));
    tabs[1].setAttribute('aria-selected', String(routeTab));
    tabs[0].tabIndex = routeTab ? -1 : 0;
    tabs[1].tabIndex = routeTab ? 0 : -1;
    $('#panel-atlas').hidden = routeTab;
    $('#panel-route').hidden = !routeTab;
    $('#tab-route-count').textContent = state.route.stops.length;
  }

  function renderDrawer(state) {
    $('#app').dataset.sidebar = state.sidebarOpen ? 'open' : 'closed';
    $('#sidebar-toggle').setAttribute('aria-expanded', String(state.sidebarOpen));
    $('#sidebar-toggle').setAttribute('aria-label', state.sidebarOpen ? 'Hide the atlas panel' : 'Show the atlas panel');
    $('#scrim').hidden = !state.sidebarOpen;
  }

  return {
    render(state, changed, visible) {
      const all = !changed;
      if (all || changed.has('group') || changed.has('query') || changed.has('year')) renderFilters(state);
      if (all || ['group', 'query', 'year', 'selectedId', 'route'].some((k) => changed.has(k))) renderList(state, visible);
      if (all || changed.has('tab') || changed.has('route')) renderTabs(state);
      if (all || changed.has('sidebarOpen')) renderDrawer(state);
    },
    scrollToSelected(id) {
      list.querySelector(`[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' });
    },
  };
}
