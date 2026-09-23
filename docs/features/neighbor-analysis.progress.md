# Neighbor Analysis — progress

Detailed dated log for this blueprint. Brief: [`neighbor-analysis.md`](neighbor-analysis.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

---
## From brief History (migrated 2026-09-17)

- 2026-08-17: 5G-5G + azimuth/freshness.
- 2026-08-31: Export Excel on the analysis page; JS `||` for Content-Disposition (not Python `or`).

## 2026-08-31 (platform hygiene)

**NEXT:** Rebuild SON ML so Topology can use the raised neighbor-line cap (`NEIGHBOR_MAX_LINES=100000`). Then click through `/son-analytics` in a browser (no browser MCP this session; APIs were verified via Flask test client).

## 2026-08-31 (platform hygiene)

- Done: Custom HTML 404 (`templates/404.html`, NexusCore constellation) + JSON `{"error":"Not found"}` for `/api/*`. Flask test client: HTML 404, API 404.
- Done: Public `/robots.txt` (`User-agent: *` / `Disallow: /`). `X-Robots-Tag: noindex, nofollow` on all responses.
- Done: Neighbor Relations Analyzer Excel export — `/api/network-map/neighbors/export` + **Export Excel** on `/neighbor-analysis`. Same filters as map lines. Workbook builder verified (`PK` xlsx). Live neighbor DB returned 0 lines in this session (export would 400 until a cell is drawn).
- **NEXT:** SON ML rebuild (above). Postgres cutover is opt-in on the server (`NCM_DATABASE_URL`); this laptop stays SQLite.
