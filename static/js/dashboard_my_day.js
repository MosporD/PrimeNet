/**
 * Dashboard My Day strip — loads GET /api/dashboard/my-day and renders cards.
 * Honest empties only; no invented KPIs.
 */
(function () {
  'use strict';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function iconStack() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3 3 7.5 12 12l9-4.5L12 3Z"/><path d="M3 12.5 12 17l9-4.5"/><path d="M3 17.5 12 22l9-4.5"/></svg>';
  }
  function iconClock() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 1.5"/></svg>';
  }
  function iconHome() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5"/><path d="M6 10.5V19h12v-8.5"/><path d="M10 19v-5h4v5"/></svg>';
  }
  function iconArrow() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 12h12"/><path d="m12 6 6 6-6 6"/></svg>';
  }
  function iconStar() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m12 3.5 2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.2 7.2 18.4l.9-5.4-3.9-3.8 5.4-.8L12 3.5Z"/></svg>';
  }

  function renderNeeds(card, data) {
    const urgent = !data.empty && data.total > 0;
    card.classList.toggle('is-urgent', urgent);
    const badge = card.querySelector('[data-my-day-badge]');
    if (badge) {
      badge.hidden = !urgent;
      badge.textContent = urgent ? String(data.total) : '';
    }
    const body = card.querySelector('[data-my-day-body]');
    if (!body) return;
    if (data.empty) {
      body.innerHTML =
        '<div class="day-card-body day-empty">' +
        '<p class="day-metric">Clear</p>' +
        '<p>' + esc(data.message || 'Nothing assigned to you right now.') + '</p>' +
        '</div>' +
        '<a class="day-cta day-cta-ghost" href="' + esc(data.href || '/optimization-cases') + '">Browse cases</a>';
      return;
    }
    body.innerHTML =
      '<div class="day-card-body"><ul class="day-list">' +
      '<li><a href="' + esc(data.href) + '">Cases assigned</a><span class="meta">' + esc(data.assigned) + ' open</span></li>' +
      '<li><a href="' + esc(data.href) + '">Awaiting verification</a><span class="meta">' + esc(data.awaiting_verification) + '</span></li>' +
      '<li><a href="' + esc(data.href) + '">Approvals pending</a><span class="meta">' + esc(data.approvals_pending) + '</span></li>' +
      '</ul></div>' +
      '<a class="day-cta" href="' + esc(data.href) + '">Open Optimization Cases</a>';
  }

  function renderSince(card, data) {
    const body = card.querySelector('[data-my-day-body]');
    if (!body) return;
    if (data.empty) {
      body.innerHTML =
        '<div class="day-card-body day-empty">' +
        '<p>' + esc(data.message || 'No network changes logged since your last visit.') + '</p>' +
        '</div>';
      return;
    }
    const away =
      data.away_hours != null
        ? '<p class="day-metric">Away ' + esc(data.away_hours) + 'h</p>'
        : '';
    const items = (data.items || [])
      .map(function (item) {
        const text = esc(item.text || '');
        if (item.href) {
          return '<li><a href="' + esc(item.href) + '">' + text + '</a></li>';
        }
        return '<li><span>' + text + '</span></li>';
      })
      .join('');
    body.innerHTML =
      '<div class="day-card-body">' + away + '<ul class="day-list">' + items + '</ul></div>';
  }

  function renderWatchlist(card, data) {
    const body = card.querySelector('[data-my-day-body]');
    if (!body) return;
    if (!data.configured) {
      body.innerHTML =
        '<div class="day-card-body day-empty">' +
        '<p>' + esc(data.message || 'Set a cluster, region, or site list to watch.') + '</p>' +
        '<p>Movers will show here against your baseline when connected.</p>' +
        '</div>' +
        '<a class="day-cta" href="/user-profile">Set watchlist</a>';
      return;
    }
    body.innerHTML =
      '<div class="day-card-body">' +
      '<p><strong>' + esc(data.label) + '</strong> · ' + esc(data.scope || 'watchlist') + '</p>' +
      '<p class="day-watchlist-note">' + esc(data.message || '') + '</p>' +
      '</div>' +
      '<a class="day-cta" href="' + esc(data.href || '/network-health') + '">Open watchlist</a>';
  }

  function renderContinue(card, data) {
    const body = card.querySelector('[data-my-day-body]');
    if (!body) return;
    if (data.empty) {
      body.innerHTML =
        '<div class="day-card-body day-empty">' +
        '<p>' + esc(data.message || 'Tools you open will show up here.') + '</p>' +
        '<p>Last filters are restored when available.</p>' +
        '</div>';
      return;
    }
    const rows = (data.items || [])
      .map(function (item) {
        const chips = (item.filters || [])
          .map(function (f) {
            return '<span class="filter-chip">' + esc(f) + '</span>';
          })
          .join('');
        return (
          '<div class="continue-item">' +
          '<a href="' + esc(item.href) + '">' + esc(item.name) + '</a>' +
          (chips ? '<div class="filter-chips">' + chips + '</div>' : '') +
          '</div>'
        );
      })
      .join('');
    body.innerHTML = '<div class="day-card-body">' + rows + '</div>';
  }

  function renderFirstRun(data) {
    const section = document.getElementById('dashboard-first-run');
    if (!section) return;
    const show = !!(data && data.show);
    section.hidden = !show;
    if (!show) return;
    const list = section.querySelector('[data-first-run-steps]');
    if (!list) return;
    list.innerHTML = (data.steps || [])
      .map(function (step) {
        return (
          '<li>' +
          '<span class="check-box" aria-hidden="true"></span>' +
          '<div class="step-body"><strong>' +
          esc(step.title) +
          '</strong><span>' +
          esc(step.detail) +
          '</span></div>' +
          '<a class="step-link" href="' +
          esc(step.href || '#') +
          '">' +
          esc(step.action_label || 'Open') +
          '</a>' +
          '</li>'
        );
      })
      .join('');
  }

  function renderPinNudge(suggestions, favoritesCount) {
    const nudge = document.getElementById('dashboard-pin-nudge');
    const pinned = document.getElementById('dashboard-pinned-tools');
    if (!nudge) return;
    const show = (!favoritesCount || favoritesCount === 0) && suggestions && suggestions.length;
    nudge.hidden = !show;
    if (pinned && show) {
      // Keep pinned section hidden while teaching empty state.
      pinned.hidden = true;
    }
    if (!show) return;
    const grid = nudge.querySelector('[data-pin-suggestions]');
    if (!grid) return;
    grid.innerHTML = suggestions
      .map(function (item) {
        return (
          '<a class="suggest-card" href="' +
          esc(item.href) +
          '">' +
          '<span class="suggest-star" aria-hidden="true">' +
          iconStar() +
          '</span>' +
          '<span><strong>' +
          esc(item.name) +
          '</strong><span>Suggested for your role</span></span>' +
          '</a>'
        );
      })
      .join('');
  }

  function setSubtitle(text) {
    const el = document.getElementById('my-day-sub');
    if (el) el.textContent = text;
  }

  async function loadMyDay() {
    const root = document.getElementById('dashboard-my-day');
    if (!root) return;
    try {
      const res = await fetch('/api/dashboard/my-day', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if (!data || data.success === false) throw new Error(data && data.error ? data.error : 'failed');

      renderNeeds(document.getElementById('my-day-needs'), data.needs_you || { empty: true });
      renderSince(document.getElementById('my-day-since'), data.since_last_visit || { empty: true });
      renderWatchlist(document.getElementById('my-day-watchlist'), data.watchlist || { configured: false, empty: true });
      renderContinue(document.getElementById('my-day-continue'), data.continue || { empty: true });
      renderFirstRun(data.first_run || { show: false });
      renderPinNudge(data.pin_suggestions || [], data.favorites_count || 0);

      if (data.first_run && data.first_run.show) {
        setSubtitle('First visit setup · checklist + pin suggestions');
      } else if (data.needs_you && !data.needs_you.empty) {
        setSubtitle('Personal to you · updated for this login');
      } else {
        setSubtitle('Quiet day · cards stay honest when there is nothing to show');
      }
      root.hidden = false;
    } catch (err) {
      console.warn('My Day unavailable', err);
      root.hidden = false;
      setSubtitle('My Day unavailable right now');
    }
  }

  window.loadDashboardMyDay = loadMyDay;

  document.addEventListener('DOMContentLoaded', function () {
    // Preferences load may race pin render; My Day pin nudge re-checks after fetch.
    loadMyDay();
  });
})();
