# Repeater data for Network Map

Place your manual repeater spreadsheet here (`.xlsx`, `.xls`, or `.csv`).

The app reads the **newest raw file** (not `*_cleaned*`) and writes a deduplicated copy next to it, e.g. `Repeater Master sheet Apr-2026_cleaned.csv`. Open that file to review one row per repeater. Regenerate anytime:

```bash
python scripts/clean_repeater_sheet.py
```

Expected columns include at least:

- **Latitude** / **Longitude**
- **Site_name** (or neighborhood as fallback)
- **Refcode** (work order / request id)
- **Rep_Serial_Num** — unique repeater id (only dedupe key; duplicate serials → keep latest **Submit_Date**)
- **Refcode** — work order / request id (not used for deduplication)
- **Repeater_Type**, **Repeater_Manufacture**, **Status**, **Remedy_Action**, etc.

On the Network Map page, enable **Show repeaters** and apply a technology filter or search to load markers.
