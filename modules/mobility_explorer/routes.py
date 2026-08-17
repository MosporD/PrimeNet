from core.radio.blueprint import make_radio_module
from core.radio.mobility import mobility_explorer

mobility_explorer_bp = make_radio_module(
    name="mobility_explorer",
    href="/mobility-explorer",
    title="Mobility / HO Explorer",
    subtitle="Relation-level handover SR, one-way neighbors, attempts, and distance — a HO workbook, not a map.",
    kind="mobility-explorer",
    api_url="/api/mobility-explorer/issues",
    builder=mobility_explorer,
    default_technology="4G-4G",
)
