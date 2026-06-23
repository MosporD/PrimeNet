/**
 * Saved Views / Shareable Links — reusable component.
 *
 * A page registers itself by calling `attachSavedViews({...})` once and
 * supplying:
 *   - module:      stable identifier ("network_map", "performance", ...)
 *   - mountSelector: where to insert the toolbar (a CSS selector string)
 *   - getState():  function that returns a JSON-serializable snapshot of
 *                  the current filters / UI state.
 *   - applyState(state, opts): function that restores a previously saved
 *                  state. opts.fromUrl indicates an initial URL load.
 *   - autoApplyOnLoad (optional bool, default true): apply ?view_id from
 *                  the URL on mount.
 *
 * Behaviour:
 *   - "Save view" prompts for a name and POSTs to /api/profile/views.
 *   - The dropdown lists all of the user's saved views for this module.
 *   - "Copy share link" copies a URL containing ?view_id=<id> for the
 *     selected view; if the view is not yet shareable it will be marked
 *     public on the server first (after explicit user confirmation).
 *   - On load, if the URL contains ?view_id=<id>, the matching view is
 *     fetched and applied via the page-supplied applyState callback.
 */

(function () {
    'use strict';

    if (window.PrimeNetSavedViews) return;

    const VIEW_QUERY_PARAM = 'view_id';

    function _safeFetchJson(url, opts = {}) {
        return fetch(url, Object.assign({ credentials: 'same-origin' }, opts))
            .then(async (r) => {
                let body = null;
                try { body = await r.json(); } catch (_) { /* ignore */ }
                return { ok: r.ok, status: r.status, body };
            });
    }

    function _toast(message, kind) {
        try {
            if (typeof window.showNotification === 'function') {
                window.showNotification(message, kind || 'info');
                return;
            }
        } catch (_) { /* ignore */ }
        window.alert(message);
    }

    function _stripViewIdFromUrl() {
        try {
            const url = new URL(window.location.href);
            if (url.searchParams.has(VIEW_QUERY_PARAM)) {
                url.searchParams.delete(VIEW_QUERY_PARAM);
                window.history.replaceState({}, '', url.toString());
            }
        } catch (_) { /* ignore */ }
    }

    function _buildShareLink(viewId) {
        try {
            const url = new URL(window.location.href);
            url.searchParams.set(VIEW_QUERY_PARAM, viewId);
            return url.toString();
        } catch (_) {
            const base = String(window.location.origin || '') + String(window.location.pathname || '');
            return `${base}?${VIEW_QUERY_PARAM}=${encodeURIComponent(viewId)}`;
        }
    }

    async function _copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch (_) { /* fallback below */ }
        }
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            return ok;
        } catch (_) {
            return false;
        }
    }

    function _renderToolbar(host, state) {
        host.classList.add('saved-views-bar');
        host.innerHTML = `
            <span class="saved-views-label" title="Saved Views &amp; Share Links">⭐ Views</span>
            <select class="saved-views-select" data-role="select" aria-label="Saved views"></select>
            <button type="button" class="saved-views-btn" data-role="open" title="Open selected view">Open</button>
            <button type="button" class="saved-views-btn" data-role="save" title="Save current filters as a view">Save</button>
            <button type="button" class="saved-views-btn" data-role="share" title="Copy a shareable link to the selected view">Share</button>
            <button type="button" class="saved-views-btn saved-views-btn-danger" data-role="delete" title="Delete selected view">Delete</button>
        `;
        return {
            select: host.querySelector('[data-role="select"]'),
            openBtn: host.querySelector('[data-role="open"]'),
            saveBtn: host.querySelector('[data-role="save"]'),
            shareBtn: host.querySelector('[data-role="share"]'),
            deleteBtn: host.querySelector('[data-role="delete"]'),
        };
    }

    function _populateSelect(select, views, selectedId) {
        const placeholder = '<option value="">— Select a saved view —</option>';
        const opts = (views || []).map((v) => {
            const label = v.is_public ? `${v.name} · shared` : v.name;
            return `<option value="${v.id}">${_esc(label)}</option>`;
        }).join('');
        select.innerHTML = placeholder + opts;
        if (selectedId) select.value = selectedId;
    }

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function _refreshList(state) {
        const { module, controls } = state;
        const res = await _safeFetchJson(`/api/profile/views?module=${encodeURIComponent(module)}`);
        if (res.ok && res.body && res.body.success) {
            state.views = Array.isArray(res.body.views) ? res.body.views : [];
        } else {
            state.views = [];
        }
        const previouslySelected = controls.select.value;
        _populateSelect(controls.select, state.views, previouslySelected);
    }

    async function _saveCurrent(state) {
        const { module, getState, controls } = state;
        const defaultName = (state.lastSavedName || '').trim();
        const name = window.prompt('Name this view (max 80 chars):', defaultName || 'My view');
        if (name == null) return;
        const trimmed = String(name).trim();
        if (!trimmed) {
            _toast('Please enter a non-empty name.', 'error');
            return;
        }
        let snapshot;
        try {
            snapshot = getState() || {};
        } catch (e) {
            _toast('Could not read current view state.', 'error');
            return;
        }
        const res = await _safeFetchJson('/api/profile/views', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ module, name: trimmed, state: snapshot, is_public: false }),
        });
        if (!res.ok || !res.body || !res.body.success) {
            const msg = (res.body && (res.body.error || res.body.message)) || 'Save failed.';
            _toast(msg, 'error');
            return;
        }
        state.lastSavedName = trimmed;
        await _refreshList(state);
        controls.select.value = res.body.id;
        _toast(`Saved view "${trimmed}".`, 'success');
    }

    async function _openSelected(state) {
        const { applyState, controls } = state;
        const id = controls.select.value;
        if (!id) {
            _toast('Pick a view from the dropdown first.', 'info');
            return;
        }
        const res = await _safeFetchJson(`/api/profile/views/${encodeURIComponent(id)}`);
        if (!res.ok || !res.body || !res.body.success) {
            const msg = (res.body && (res.body.error || res.body.message)) || 'Could not load view.';
            _toast(msg, 'error');
            return;
        }
        const view = res.body.view || {};
        try {
            await applyState(view.state || {}, { fromUrl: false, view });
            _toast(`Opened "${view.name}".`, 'success');
        } catch (e) {
            _toast('Failed to apply view.', 'error');
        }
    }

    async function _shareSelected(state) {
        const { controls } = state;
        const id = controls.select.value;
        if (!id) {
            _toast('Pick a view to share.', 'info');
            return;
        }
        const view = (state.views || []).find((v) => v.id === id);
        if (!view) {
            _toast('Selected view is no longer available.', 'error');
            return;
        }
        if (!view.is_public) {
            const proceed = window.confirm(
                `Sharing "${view.name}" will make it openable by other PrimeNet users with the link. Continue?`
            );
            if (!proceed) return;
            const detail = await _safeFetchJson(`/api/profile/views/${encodeURIComponent(id)}`);
            const stateBlob = (detail.body && detail.body.view && detail.body.view.state) || {};
            const upd = await _safeFetchJson('/api/profile/views', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ module: state.module, name: view.name, state: stateBlob, is_public: true }),
            });
            if (!upd.ok || !upd.body || !upd.body.success) {
                _toast('Could not enable sharing for this view.', 'error');
                return;
            }
            await _refreshList(state);
            controls.select.value = id;
        }
        const link = _buildShareLink(id);
        const ok = await _copyText(link);
        if (ok) {
            _toast('Share link copied to clipboard.', 'success');
        } else {
            window.prompt('Copy this share link:', link);
        }
    }

    async function _deleteSelected(state) {
        const { controls } = state;
        const id = controls.select.value;
        if (!id) {
            _toast('Pick a view to delete.', 'info');
            return;
        }
        const view = (state.views || []).find((v) => v.id === id);
        const label = view ? `"${view.name}"` : 'this view';
        if (!window.confirm(`Delete ${label}? This cannot be undone.`)) return;
        const res = await _safeFetchJson(`/api/profile/views/${encodeURIComponent(id)}`, {
            method: 'DELETE',
        });
        if (!res.ok || !res.body || !res.body.success) {
            _toast((res.body && res.body.error) || 'Delete failed.', 'error');
            return;
        }
        await _refreshList(state);
        _toast('View deleted.', 'success');
    }

    async function _applyUrlViewIfPresent(state) {
        try {
            const url = new URL(window.location.href);
            const id = url.searchParams.get(VIEW_QUERY_PARAM);
            if (!id) return false;
            const res = await _safeFetchJson(`/api/profile/views/${encodeURIComponent(id)}`);
            if (!res.ok || !res.body || !res.body.success) {
                _toast('That share link is no longer available.', 'error');
                _stripViewIdFromUrl();
                return false;
            }
            const view = res.body.view || {};
            await state.applyState(view.state || {}, { fromUrl: true, view });
            // Keep the user on a clean URL once we've applied the view.
            _stripViewIdFromUrl();
            _toast(`Opened shared view "${view.name}".`, 'success');
            return true;
        } catch (_) {
            return false;
        }
    }

    function attachSavedViews(opts) {
        if (!opts || typeof opts !== 'object') return null;
        const module = String(opts.module || '').trim();
        const getState = typeof opts.getState === 'function' ? opts.getState : null;
        const applyState = typeof opts.applyState === 'function' ? opts.applyState : null;
        const mountSelector = String(opts.mountSelector || '').trim();
        const autoApplyOnLoad = opts.autoApplyOnLoad !== false;
        if (!module || !getState || !applyState || !mountSelector) {
            console.warn('[saved-views] missing required options', opts);
            return null;
        }

        const host = document.querySelector(mountSelector);
        if (!host) {
            console.warn('[saved-views] mount selector not found:', mountSelector);
            return null;
        }

        const state = {
            module,
            getState,
            applyState,
            views: [],
            controls: null,
            lastSavedName: '',
        };
        state.controls = _renderToolbar(host, state);

        state.controls.saveBtn.addEventListener('click', () => _saveCurrent(state));
        state.controls.openBtn.addEventListener('click', () => _openSelected(state));
        state.controls.shareBtn.addEventListener('click', () => _shareSelected(state));
        state.controls.deleteBtn.addEventListener('click', () => _deleteSelected(state));

        // Initial population.
        _refreshList(state).then(() => {
            if (autoApplyOnLoad) {
                _applyUrlViewIfPresent(state);
            }
        });

        return {
            refresh: () => _refreshList(state),
            saveCurrent: () => _saveCurrent(state),
            applyUrlIfPresent: () => _applyUrlViewIfPresent(state),
        };
    }

    window.PrimeNetSavedViews = { attach: attachSavedViews };
})();
