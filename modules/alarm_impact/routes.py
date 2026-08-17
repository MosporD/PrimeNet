from core.radio.alarm_impact import alarm_impact
from core.radio.blueprint import make_radio_module

alarm_impact_bp = make_radio_module(
    name="alarm_impact",
    href="/alarm-impact",
    title="Alarm–PM Correlator",
    subtitle="Is it sleeping, or is it alarmed? Live FM plus daily PM collapse plus CM-active state.",
    kind="alarm-impact",
    api_url="/api/alarm-impact/issues",
    builder=alarm_impact,
    default_technology="all",
)
