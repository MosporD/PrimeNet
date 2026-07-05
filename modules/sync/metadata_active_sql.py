"""
Vendor-specific cell operational state (on-air vs offline).

Rules
-----
* 2G: Huawei → column ``active_state`` (Activated = on-air, Deactivated = off).
      Nokia  → column ``admin_state`` (Unlocked = on-air, Locked = off).
* 3G, 5G: Huawei ``active_state`` Activated/Deactivated; Nokia ``active_state`` Unlocked/Locked.
* 4G FDD: ``active_state`` — Huawei **Activated or CELL_ACTIVE**; Nokia **Unlocked or CELL_ACTIVE**.
* 4G TDD: Huawei ``active_state`` CELL_ACTIVE / CELL_INACTIVE; Nokia ``admin_state``
  Unlocked (same as 2G Nokia), not ``active_state``.

Normalized matching: LOWER(TRIM(...)). Vendor: LOWER(TRIM(vendor)) in huawei|nokia.

The network map union exposes this as ``activity_status`` ('Active' | 'Inactive').
``status`` is kept as an alias of ``activity_status`` for older clients.
"""

# Normalised vendor match (CSV uses "Huawei" / "Nokia")
_VH = "LOWER(TRIM(COALESCE(vendor, ''))) = 'huawei'"
_VN = "LOWER(TRIM(COALESCE(vendor, ''))) = 'nokia'"


def _activity_case_2g() -> str:
    """Huawei: active_state activated. Nokia: admin_state unlocked."""
    return f"""
    CASE
      WHEN {_VH}
           AND LOWER(TRIM(COALESCE(active_state, ''))) = 'activated'
        THEN 'Active'
      WHEN {_VN}
           AND LOWER(TRIM(COALESCE(admin_state, ''))) = 'unlocked'
        THEN 'Active'
      ELSE 'Inactive'
    END
"""


def _activity_case_active_state_huawei_activated_nokia_unlocked() -> str:
    """One column active_state: Huawei activated; Nokia unlocked."""
    return f"""
    CASE
      WHEN {_VH}
           AND LOWER(TRIM(COALESCE(active_state, ''))) = 'activated'
        THEN 'Active'
      WHEN {_VN}
           AND LOWER(TRIM(COALESCE(active_state, ''))) = 'unlocked'
        THEN 'Active'
      ELSE 'Inactive'
    END
"""


def _activity_case_4g_fdd() -> str:
    """LTE FDD: Huawei activated or cell_active; Nokia unlocked or cell_active (same column)."""
    return f"""
    CASE
      WHEN {_VH}
           AND LOWER(TRIM(COALESCE(active_state, ''))) IN ('activated', 'cell_active')
        THEN 'Active'
      WHEN {_VN}
           AND LOWER(TRIM(COALESCE(active_state, ''))) IN ('unlocked', 'cell_active')
        THEN 'Active'
      ELSE 'Inactive'
    END
    """


def _activity_case_4g_tdd() -> str:
    """Huawei: CELL_ACTIVE. Nokia: admin_state unlocked (same as 2G Nokia)."""
    return f"""
    CASE
      WHEN {_VH}
           AND LOWER(TRIM(COALESCE(active_state, ''))) = 'cell_active'
        THEN 'Active'
      WHEN {_VN}
           AND LOWER(TRIM(COALESCE(admin_state, ''))) = 'unlocked'
        THEN 'Active'
      ELSE 'Inactive'
    END
    """


# SQL expressions for ON-AIR predicates (filters, future use)
def where_cells_2g_active() -> str:
    return f"""(
      ({_VH} AND LOWER(TRIM(COALESCE(active_state, ''))) = 'activated')
      OR
      ({_VN} AND LOWER(TRIM(COALESCE(admin_state, ''))) = 'unlocked')
    )"""


def where_cells_3g_active() -> str:
    return f"""(
      ({_VH} AND LOWER(TRIM(COALESCE(active_state, ''))) = 'activated')
      OR
      ({_VN} AND LOWER(TRIM(COALESCE(active_state, ''))) = 'unlocked')
    )"""


def where_cells_4g_fdd_active() -> str:
    return f"""(
      ({_VH} AND LOWER(TRIM(COALESCE(active_state, ''))) IN ('activated', 'cell_active'))
      OR
      ({_VN} AND LOWER(TRIM(COALESCE(active_state, ''))) IN ('unlocked', 'cell_active'))
    )"""


def where_cells_4g_tdd_active() -> str:
    return f"""(
      ({_VH} AND LOWER(TRIM(COALESCE(active_state, ''))) = 'cell_active')
      OR
      ({_VN} AND LOWER(TRIM(COALESCE(admin_state, ''))) = 'unlocked')
    )"""


def where_cells_5g_active() -> str:
    return where_cells_3g_active()


PER_TABLE_ACTIVE_WHERE = {
    'cells_2g': where_cells_2g_active(),
    'cells_3g': where_cells_3g_active(),
    'cells_4g_fdd': where_cells_4g_fdd_active(),
    'cells_4g_tdd': where_cells_4g_tdd_active(),
    'cells_5g': where_cells_5g_active(),
}

# Map union: one computed column (and alias for compatibility)
_ACTIVITY_STATUS_2G = _activity_case_2g()
_ACTIVITY_STATUS_3G_FDD = _activity_case_active_state_huawei_activated_nokia_unlocked()
_ACTIVITY_STATUS_4G_FDD = _activity_case_4g_fdd()
_ACTIVITY_STATUS_4G_TDD = _activity_case_4g_tdd()
_ACTIVITY_STATUS_5G = _activity_case_active_state_huawei_activated_nokia_unlocked()

# Backward-compatible names used by network_map routes imports
_STATUS_2G = _ACTIVITY_STATUS_2G
_STATUS_3G_FDD = _ACTIVITY_STATUS_3G_FDD
_STATUS_4G_FDD = _ACTIVITY_STATUS_4G_FDD
_STATUS_4G_TDD = _ACTIVITY_STATUS_4G_TDD
_STATUS_5G = _ACTIVITY_STATUS_5G

# Legacy `cells` table refresh: same rules as the map union
LEGACY_CELLS_ACTIVITY_CASE_SQL = {
    'cells_2g': _activity_case_2g(),
    'cells_3g': _activity_case_active_state_huawei_activated_nokia_unlocked(),
    'cells_4g_fdd': _activity_case_4g_fdd(),
    'cells_4g_tdd': _activity_case_4g_tdd(),
    'cells_5g': _activity_case_active_state_huawei_activated_nokia_unlocked(),
}


def legacy_cells_activity_case_sql(table_name: str) -> str:
    """SQL CASE expression → 'Active' | 'Inactive' for INSERT into legacy cells.status."""
    return LEGACY_CELLS_ACTIVITY_CASE_SQL[table_name]


def perf_per_tech_union_sql() -> str:
    """Performance metadata union: all cell rows (same scope as network map data)."""
    return """
        SELECT
            cell_name,
            site_id AS site_id,
            site_name AS site_name,
            '2G' AS technology,
            vendor,
            frequency_band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(COALESCE(NULLIF(TRIM(bcch), ''), NULLIF(TRIM(bcc), '')) AS INTEGER) AS pci
        FROM cells_2g
        UNION ALL
        SELECT
            cell_name,
            nodeb_id AS site_id,
            nodeb_name AS site_name,
            '3G' AS technology,
            vendor,
            dl_uarfcn AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(psc AS INTEGER) AS pci
        FROM cells_3g
        UNION ALL
        SELECT
            cell_name,
            enb_id_actual AS site_id,
            enb_name AS site_name,
            '4G-FDD' AS technology,
            vendor,
            band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(pci AS INTEGER) AS pci
        FROM cells_4g_fdd
        UNION ALL
        SELECT
            cell_name,
            enb_id_actual AS site_id,
            enb_name AS site_name,
            '4G-TDD' AS technology,
            vendor,
            band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(pci AS INTEGER) AS pci
        FROM cells_4g_tdd
        UNION ALL
        SELECT
            cell_name,
            gnb_id_actual AS site_id,
            gnb_name AS site_name,
            '5G' AS technology,
            vendor,
            bw AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(pci AS INTEGER) AS pci
        FROM cells_5g
    """


def perf_per_tech_union_sql_with_activity() -> str:
    """Same as ``perf_per_tech_union_sql`` plus ``activity_status`` (Active / Inactive)."""
    return f"""
        SELECT
            cell_name,
            site_id AS site_id,
            site_name AS site_name,
            '2G' AS technology,
            vendor,
            frequency_band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(COALESCE(NULLIF(TRIM(bcch), ''), NULLIF(TRIM(bcc), '')) AS INTEGER) AS pci,
            {_STATUS_2G} AS activity_status
        FROM cells_2g
        UNION ALL
        SELECT
            cell_name,
            nodeb_id AS site_id,
            nodeb_name AS site_name,
            '3G' AS technology,
            vendor,
            dl_uarfcn AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(psc AS INTEGER) AS pci,
            {_STATUS_3G_FDD} AS activity_status
        FROM cells_3g
        UNION ALL
        SELECT
            cell_name,
            enb_id_actual AS site_id,
            enb_name AS site_name,
            '4G-FDD' AS technology,
            vendor,
            band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(pci AS INTEGER) AS pci,
            {_STATUS_4G_FDD} AS activity_status
        FROM cells_4g_fdd
        UNION ALL
        SELECT
            cell_name,
            enb_id_actual AS site_id,
            enb_name AS site_name,
            '4G-TDD' AS technology,
            vendor,
            band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(pci AS INTEGER) AS pci,
            {_STATUS_4G_TDD} AS activity_status
        FROM cells_4g_tdd
        UNION ALL
        SELECT
            cell_name,
            gnb_id_actual AS site_id,
            gnb_name AS site_name,
            '5G' AS technology,
            vendor,
            bw AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(pci AS INTEGER) AS pci,
            {_STATUS_5G} AS activity_status
        FROM cells_5g
    """


def perf_cell_source_sql_with_activity(technology: str | None = None) -> str:
    """Metadata cell rows for Performance — one RAT table when possible (avoids 5-way UNION)."""
    tech = str(technology or '').strip()
    if tech == '2G':
        return f"""
        SELECT
            cell_name, site_id AS site_id, site_name AS site_name,
            '2G' AS technology, vendor, frequency_band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth,
            CAST(COALESCE(NULLIF(TRIM(bcch), ''), NULLIF(TRIM(bcc), '')) AS INTEGER) AS pci,
            {_STATUS_2G} AS activity_status
        FROM cells_2g"""
    if tech == '3G':
        return f"""
        SELECT
            cell_name, nodeb_id AS site_id, nodeb_name AS site_name,
            '3G' AS technology, vendor, dl_uarfcn AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth, CAST(psc AS INTEGER) AS pci,
            {_STATUS_3G_FDD} AS activity_status
        FROM cells_3g"""
    if tech == '4G-FDD':
        return f"""
        SELECT
            cell_name, enb_id_actual AS site_id, enb_name AS site_name,
            '4G-FDD' AS technology, vendor, band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth, CAST(pci AS INTEGER) AS pci,
            {_STATUS_4G_FDD} AS activity_status
        FROM cells_4g_fdd"""
    if tech == '4G-TDD':
        return f"""
        SELECT
            cell_name, enb_id_actual AS site_id, enb_name AS site_name,
            '4G-TDD' AS technology, vendor, band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth, CAST(pci AS INTEGER) AS pci,
            {_STATUS_4G_TDD} AS activity_status
        FROM cells_4g_tdd"""
    if tech == '5G':
        return f"""
        SELECT
            cell_name, gnb_id_actual AS site_id, gnb_name AS site_name,
            '5G' AS technology, vendor, bw AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth, CAST(pci AS INTEGER) AS pci,
            {_STATUS_5G} AS activity_status
        FROM cells_5g"""
    if tech == '4G':
        return f"""
        SELECT
            cell_name, enb_id_actual AS site_id, enb_name AS site_name,
            '4G-FDD' AS technology, vendor, band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth, CAST(pci AS INTEGER) AS pci,
            {_STATUS_4G_FDD} AS activity_status
        FROM cells_4g_fdd
        UNION ALL
        SELECT
            cell_name, enb_id_actual AS site_id, enb_name AS site_name,
            '4G-TDD' AS technology, vendor, band AS frequency_band,
            CAST(azimuth AS REAL) AS azimuth, CAST(pci AS INTEGER) AS pci,
            {_STATUS_4G_TDD} AS activity_status
        FROM cells_4g_tdd"""
    return perf_per_tech_union_sql_with_activity()
