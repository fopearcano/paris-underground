// Timeline: a year slider plus a ribbon showing each location's period(s) of significance.

import { matchesGroup, matchesQuarter, matchesQuery, queryTokens } from './atlas.js';
import { $, h, plural } from './utils.js';

export function initTimeline({ atlas, store }) {
  const root = $('#timeline');
  const slider = $('#year');
  const title = $('#timeline-title');
  const showAll = $('#timeline-all');
  const ribbon = $('#timeline-ribbon');
  const labels = $('#timeline-labels');
  const { start, end, ticks } = atlas.timeline;
  const span = end - start;
  const pct = (year) => `${((Math.min(Math.max(year, start), end) - start) / span) * 100}%`;

  slider.min = start;
  slider.max = end;
  labels.replaceChildren(...ticks.map((year) => h('span', { style: { left: pct(year) } }, year)));

  // One thin row per location, in atlas order; each period is a bar on the shared scale.
  const rowHeight = 100 / atlas.locations.length;
  const bars = [];
  atlas.locations.forEach((loc, row) => {
    for (const period of loc.periods) {
      const bar = h('span', {
        class: 'tl-bar',
        style: {
          '--c': loc.color,
          left: pct(period.start),
          width: `calc(${pct(period.end ?? end)} - ${pct(period.start)} + 2px)`,
          top: `${row * rowHeight}%`,
        },
      });
      bars.push({ bar, loc, period });
      ribbon.append(bar);
    }
  });
  const cursor = h('span', { class: 'tl-cursor', hidden: true });
  ribbon.append(cursor);

  slider.addEventListener('input', () => store.set({ year: Number(slider.value) }));
  showAll.addEventListener('click', () => store.set({ year: null }));

  return {
    render(state, visible) {
      const all = state.year === null;
      root.classList.toggle('is-all', all);
      showAll.disabled = all;
      cursor.hidden = all;
      if (all) {
        title.textContent = `All periods · ${start}–${end}`;
      } else {
        if (Number(slider.value) !== state.year) slider.value = state.year;
        cursor.style.left = pct(state.year);
        title.textContent = `${state.year} · ${plural(visible.length, 'place')} active`;
      }
      slider.setAttribute('aria-valuetext', all ? `All periods, ${start} to ${end}` : `${state.year}: ${plural(visible.length, 'place')} historically active`);

      const tokens = queryTokens(state.query);
      for (const { bar, loc, period } of bars) {
        const filtered = !matchesGroup(loc, state.group) || !matchesQuarter(loc, state.quarter) || !matchesQuery(loc, tokens);
        const active = !all && state.year >= period.start && state.year <= (period.end ?? end);
        bar.classList.toggle('is-filtered', filtered);
        bar.classList.toggle('is-active', !filtered && active);
      }
    },
    rect() {
      return root.offsetParent ? root.getBoundingClientRect() : null;
    },
  };
}
