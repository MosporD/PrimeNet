# Configuration Dashboard — progress

Detailed dated log for this blueprint. Brief: [`configuration-dashboard.md`](configuration-dashboard.md).
Root journal (topics only): [`../../progress.md`](../../progress.md).

**Current track:** V1.1 WNCELG Sankey (Area → Status → groups) + Hardware tab

**NEXT:** Admin → Data Sync → Run dashboard ingest; open `/configuration-dashboard` Hardware + WNCELG Sankey tabs against live NetAct snapshot; confirm dark toggle on both tabs.

---
## 2026-09-20 (Dark mode)

- Done: Module `body.dark-mode.configuration-dashboard-page` rules + global `theme-dark-final.css` safety net (buttons/tables/chips no longer stuck light).

## 2026-09-20 (WNCELG Sankey)

- Done: WNCELG tab is Area → Status → group-count Sankey with Hardware-style layer toggles (Area / Status / Groups) and Split / No split chips; detail table retained under the chart.

## 2026-09-20 (Configuration Dashboard V1.0)

- Done: New `/configuration-dashboard` with Hardware + WNCELG tabs; dashboard tile + nav replace standalone RRU card.
- Done: WNCELG snapshot store + split detection (`group_count > 1`); Excel export; APIs under `/api/configuration-dashboard/...`.
- Done: Shared ingest (RMOD_R then WNCELG); scheduler + Admin aliases; `/rru-inventory` → `?tab=hardware`.
- Tests: `test_wncelg_logic` + `test_wncelg_store`.
