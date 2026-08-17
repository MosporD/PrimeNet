from core.radio.blueprint import make_radio_module
from core.radio.groups import group_health

group_health_bp = make_radio_module(
    name="group_health",
    href="/group-health",
    title="Group / Cluster Health",
    subtitle="BSC/RNC/controller congestion from groups PM databases, with drill-down to cell PM.",
    kind="group-health",
    api_url="/api/group-health/issues",
    builder=group_health,
    default_technology="all",
)
