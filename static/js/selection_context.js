/**
 * Shared selection context — local mirror + server sync.
 * Used by Optimization Cases and Network Map (polygon → selection).
 */
(function (global) {
    const STORAGE_KEY = "primenet.selection_context.v1";
    const API = "/api/selection-context";

    function empty() {
        return {
            kind: "empty",
            cells: [],
            sites: [],
            polygon: null,
            label: "",
            source: "",
            meta: {},
            updated_at: null,
        };
    }

    function normalize(payload) {
        const raw = payload || {};
        let cells = raw.cells || [];
        if (typeof cells === "string") {
            cells = cells.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
        }
        let sites = raw.sites || [];
        if (typeof sites === "string") {
            sites = sites.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
        }
        let kind = String(raw.kind || "cells").toLowerCase();
        if (!cells.length && !sites.length && !raw.polygon) kind = "empty";
        return {
            kind,
            cells: cells.slice(0, 2000),
            sites: sites.slice(0, 500),
            polygon: Array.isArray(raw.polygon) ? raw.polygon : null,
            label: String(raw.label || ""),
            source: String(raw.source || ""),
            meta: raw.meta && typeof raw.meta === "object" ? raw.meta : {},
            updated_at: raw.updated_at || null,
        };
    }

    function readLocal() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return empty();
            return normalize(JSON.parse(raw));
        } catch (_) {
            return empty();
        }
    }

    function writeLocal(selection) {
        const norm = normalize(selection);
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(norm));
        } catch (_) { /* ignore quota */ }
        return norm;
    }

    async function fetchServer() {
        const res = await fetch(API, { credentials: "same-origin" });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || "Failed to load selection");
        return writeLocal(data.selection || empty());
    }

    async function save(selection) {
        const norm = writeLocal(selection);
        const res = await fetch(API, {
            method: "PUT",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ selection: norm }),
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || "Failed to save selection");
        return writeLocal(data.selection || norm);
    }

    async function clear() {
        writeLocal(empty());
        const res = await fetch(API, { method: "DELETE", credentials: "same-origin" });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || "Failed to clear selection");
        return writeLocal(data.selection || empty());
    }

    async function setCells(cells, opts) {
        const options = opts || {};
        return save({
            kind: "cells",
            cells,
            sites: options.sites || [],
            polygon: options.polygon || null,
            label: options.label || "",
            source: options.source || "manual",
            meta: options.meta || {},
        });
    }

    global.PrimeNetSelection = {
        empty,
        normalize,
        readLocal,
        writeLocal,
        fetchServer,
        save,
        clear,
        setCells,
    };
})(window);
