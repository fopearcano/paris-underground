// Sidebar: search, movement filters, location list, quarters, tabs and the collapsible drawer.

import { STATUS_LABELS, groupCounts, hasActiveFilters, quarterCounts } from './atlas.js';
import { $, h, plural } from './utils.js';

const FILTER_KEYS = ['group', 'quarter', 'query', 'year'];

export function initSidebar({ atlas, store, onSelect, onSelectQuarter, onToggleSidebar }) {
  const search = $('#search');
  const filters = $('#filters');
  const list = $('#place-list');
  const overview = $('#quarter-overview');
  const quartersPanel = $('#panel-quarters');
  const resultCount = $('#result-count');
  const clearButton = $('#clear-filters');
  const tabs = [...document.querySelectorAll('.tabs [role="tab"]')];
  const panels = { atlas: $('#panel-atlas'), quarters: quartersPanel, route: $('#panel-route') };

  $('#metric-locations').textContent = atlas.locations.length;
  $('#metric-movements').textContent = atlas.activeGroups.length;
  $('#tab-quarters-count').textContent = atlas.activeQuarters.length;

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
    store.set({ group: 'all', quarter: 'all', query: '', year: null, fitRequest: Date.now() });
  });

  // ---- Tabs (WAI-ARIA tabs pattern) ----
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => store.set({ tab: tab.dataset.tab }));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus();
      store.set({ tab: tabs[next].dataset.tab });
    });
  });

  // ---- Drawer / collapse ----
  $('#sidebar-toggle').addEventListener('click', () => onToggleSidebar(!store.get().sidebarOpen));
  $('#sidebar-close').addEventListener('click', () => onToggleSidebar(false));
  $('#scrim').addEventListener('click', () => onToggleSidebar(false));

  // ---- Rendering ----

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

  function sourceLinks(sources) {
    return h('p', { class: 'q-sources' }, 'Sources: ', sources.map((s, i) => [
      i ? ' · ' : null,
      h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.publisher),
    ]));
  }

  /** "Then / Today" overview of the selected quarter, above the list. */
  function renderOverview(state) {
    const quarter = atlas.quartersById.get(state.quarter);
    overview.hidden = !quarter;
    if (!quarter) {
      overview.replaceChildren();
      return;
    }
    const expanded = overview.dataset.quarter === quarter.id && overview.classList.contains('is-expanded');
    overview.dataset.quarter = quarter.id;
    overview.classList.toggle('is-expanded', expanded);
    overview.replaceChildren(
      h('div', { class: 'q-head' },
        h('div', {},
          h('span', { class: 'q-kicker' }, `Quarter · ${quarter.arrondissements}`),
          h('h2', { class: 'q-title' }, quarter.name)),
        h('button', { type: 'button', class: 'text-button', id: 'quarter-clear', onclick: () => onSelectQuarter('all') }, 'All of Paris ✕')),
      h('div', { class: 'q-then-now' },
        h('div', { class: 'q-col' }, h('span', { class: 'tn-label' }, 'Then'), h('p', {}, quarter.then)),
        h('div', { class: 'q-col' }, h('span', { class: 'tn-label tn-label--now' }, 'Today'), h('p', {}, quarter.now))),
      h('div', { class: 'q-foot' },
        h('button', {
          type: 'button',
          class: 'text-button q-more',
          'aria-expanded': String(expanded),
          onclick: (event) => {
            const open = overview.classList.toggle('is-expanded');
            event.currentTarget.setAttribute('aria-expanded', String(open));
            event.currentTarget.textContent = open ? 'Show less ↑' : 'Read the full overview ↓';
          },
        }, expanded ? 'Show less ↑' : 'Read the full overview ↓'),
        sourceLinks(quarter.sources)));
  }

  /** The Quarters tab: one card per district, with its then/today summary. */
  function renderQuarters(state) {
    const counts = quarterCounts(atlas, state);
    quartersPanel.replaceChildren(
      h('p', { class: 'quarters-intro' }, 'Six districts of underground Paris, then and now. Choose one to filter the map and list.'),
      h('ul', { class: 'quarter-cards' }, atlas.activeQuarters.map((q) => {
        const n = counts[q.id] ?? 0;
        return h('li', {},
          h('button', {
            type: 'button',
            class: 'quarter-card',
            'data-quarter': q.id,
            'aria-pressed': String(state.quarter === q.id),
            onclick: () => onSelectQuarter(q.id),
          },
          h('span', { class: 'qc-head' },
            h('span', { class: 'qc-name' }, q.name),
            h('span', { class: 'qc-count' }, plural(n, 'place'))),
          h('span', { class: 'qc-arr' }, q.arrondissements),
          h('span', { class: 'qc-line' }, h('strong', {}, 'Then '), firstSentence(q.then)),
          h('span', { class: 'qc-line' }, h('strong', {}, 'Today '), firstSentence(q.now))));
      })));
  }

  function renderList(state, visible) {
    const total = atlas.locations.length;
    const quarter = atlas.quartersById.get(state.quarter);
    const counted = visible.length === total ? plural(total, 'location') : `${visible.length} of ${plural(total, 'location')}`;
    resultCount.textContent = quarter ? `${counted} · ${quarter.name}` : counted;
    $('#tab-atlas-count').textContent = visible.length;

    if (!visible.length) {
      list.replaceChildren(h('li', { class: 'empty' },
        'No matching places.', h('br'), 'Try another movement, quarter, year or search.', h('br'),
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
          h('span', { class: 'place-sub' }, `${loc.address.street} · ${loc.quarterInfo?.name ?? loc.address.arrondissement}`),
          h('span', { class: 'place-meta' },
            h('span', { class: 'era', title: 'Period of historical significance' }, loc.periodLabel),
            h('span', { class: `status status--${loc.status.category}`, title: `Today: ${loc.status.summary}` },
              h('span', { class: 'sr-only' }, 'Today: '), STATUS_LABELS[loc.status.category]),
            inRoute ? h('span', { class: 'place-flag' }, `Route stop ${state.route.stops.indexOf(loc.id) + 1}`) : null)),
        h('span', { class: 'dot', style: { '--c': loc.color }, title: loc.groupLabels.join(', '), 'aria-hidden': 'true' })));
    }));
  }

  function renderTabs(state) {
    for (const tab of tabs) {
      const active = tab.dataset.tab === state.tab;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      panels[tab.dataset.tab].hidden = !active;
    }
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
      const has = (...keys) => all || keys.some((k) => changed.has(k));
      if (has(...FILTER_KEYS)) renderFilters(state);
      if (has('quarter')) renderOverview(state);
      if (has(...FILTER_KEYS)) renderQuarters(state);
      if (has(...FILTER_KEYS, 'selectedId', 'route')) renderList(state, visible);
      if (has('tab', 'route')) renderTabs(state);
      if (has('sidebarOpen')) renderDrawer(state);
    },
    revealOverview() {
      if (!overview.hidden) overview.scrollIntoView({ block: 'start' });
    },
    scrollToSelected(id) {
      list.querySelector(`[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' });
    },
  };
}

function firstSentence(text) {
  const match = /^.+?[.!?](?=\s|$)/.exec(text);
  return match ? match[0] : text;
}
