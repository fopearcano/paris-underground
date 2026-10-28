// Detail panel for the selected location.

import { PRECISION_LABELS, STATUS_LABELS } from './atlas.js';
import { $, h, googleMapsSearchUrl } from './utils.js';

export function initDetail({ atlas, store, onClose, onToggleRoute }) {
  const panel = $('#detail');
  const mapArea = $('#map-area');
  let renderedId = null;

  function section(title, badge, ...content) {
    return h('section', { class: 'detail-section' },
      h('h3', {}, title, badge ? h('span', { class: `badge badge--${badge.kind}`, title: badge.title }, badge.text) : null),
      ...content);
  }

  function build(loc, state) {
    const periodsDocumented = loc.periods.every((p) => p.certainty === 'documented');
    const inRoute = state.route.stops.includes(loc.id);
    const routeFull = !inRoute && state.route.stops.length >= atlas.routing.max_stops;
    const primarySource = loc.sources[0];
    const { address } = loc;

    const top = h('header', { class: 'detail-top' },
      h('div', { class: 'detail-caps' },
        h('span', { class: 'detail-kind' }, h('span', { class: 'dot', style: { '--c': loc.color }, 'aria-hidden': 'true' }), loc.groupLabels.join(' · ')),
        h('button', { type: 'button', class: 'icon-button detail-close', 'aria-label': 'Close details', onclick: onClose },
          h('span', { 'aria-hidden': 'true' }, '×'))),
      h('h2', { id: 'detail-title', tabindex: '-1' }, loc.name),
      h('div', { class: 'detail-addr' },
        `${address.street}, Paris ${address.arrondissement}`,
        address.historical_note ? h('small', {}, address.historical_note) : null));

    const facts = h('dl', { class: 'facts' },
      h('div', {}, h('dt', {}, loc.movements.length > 1 ? 'Movements' : 'Movement'), h('dd', {}, loc.movementLabels.join(', '))),
      h('div', {}, h('dt', {}, 'Period'), h('dd', {}, loc.periodLabel,
        h('small', {}, periodsDocumented ? 'Documented dates' : 'Dates partly approximate'))));

    const evidence = [
      ...loc.periods.filter((p) => p.note).map((p) => h('li', {}, h('strong', {}, `${p.label}: `), p.note)),
      ...loc.caveats.map((c) => h('li', {}, c)),
    ];

    const body = h('div', { class: 'detail-body' },
      facts,
      section('Historical record', { kind: 'documented', text: 'Documented', title: 'Supported by the sources listed below' },
        h('p', {}, loc.description)),
      loc.figures.length
        ? section('Associated figures', null, h('ul', { class: 'figures' },
          loc.figures.map((f) => h('li', {}, h('strong', {}, f.name), h('span', {}, f.role)))))
        : null,
      h('div', { class: 'today' }, section('Today', null,
        h('p', {}, h('span', { class: `status status--${loc.status.category}` }, STATUS_LABELS[loc.status.category]), loc.status.summary))),
      h('div', { class: 'detail-context' }, section('Significance', { kind: 'interpretation', text: 'Interpretation', title: 'Editorial context, not a documented fact' },
        h('p', {}, loc.significance))),
      evidence.length ? section('Dates & evidence', null, h('div', { class: 'caveats' }, h('ul', {}, evidence))) : null,
      section('Location', { kind: loc.coordinates.precision === 'approximate' ? 'approximate' : 'documented', text: loc.coordinates.precision === 'approximate' ? 'Approximate' : 'Address-level' },
        h('p', { class: 'precision' }, `${PRECISION_LABELS[loc.coordinates.precision]}. ${loc.coordinates.note ?? ''}`)),
      section('Sources', null, h('ol', { class: 'sources' }, loc.sources.map((s) =>
        h('li', {},
          h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, `${s.title} ↗`),
          h('span', {}, s.publisher))))));

    const actions = h('footer', { class: 'detail-actions' },
      h('a', { id: 'detail-source', href: primarySource.url, target: '_blank', rel: 'noopener noreferrer' }, 'View historical source ↗'),
      h('a', { id: 'detail-gmaps', href: googleMapsSearchUrl(loc), target: '_blank', rel: 'noopener noreferrer' }, 'Open in Google Maps ↗'),
      h('button', {
        type: 'button',
        id: 'detail-route',
        class: inRoute ? 'is-in-route' : null,
        'aria-pressed': String(inRoute),
        disabled: routeFull,
        title: routeFull ? `A walking route can have at most ${atlas.routing.max_stops} stops` : null,
        onclick: () => onToggleRoute(loc.id),
      }, inRoute ? `✓ Route stop ${state.route.stops.indexOf(loc.id) + 1} · remove` : '+ Add to walking route'));

    return [h('div', { class: 'detail-scroll' }, top, body), actions];
  }

  return {
    render(state) {
      const loc = state.selectedId ? atlas.locationsById.get(state.selectedId) : null;
      mapArea.classList.toggle('has-detail', Boolean(loc));
      if (!loc) {
        panel.hidden = true;
        panel.replaceChildren();
        renderedId = null;
        return;
      }
      const scroll = renderedId === loc.id ? panel.querySelector('.detail-scroll')?.scrollTop ?? 0 : 0;
      panel.replaceChildren(...build(loc, state));
      panel.hidden = false;
      panel.querySelector('.detail-scroll').scrollTop = scroll;
      renderedId = loc.id;
    },
    focusTitle() {
      panel.querySelector('#detail-title')?.focus({ preventScroll: true });
    },
    rect() {
      return panel.hidden ? null : panel.getBoundingClientRect();
    },
  };
}
