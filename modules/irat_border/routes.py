from core.radio.blueprint import make_radio_module
from core.radio.mobility import irat_border

irat_border_bp = make_radio_module(
    name="irat_border",
    href="/irat-border",
    title="IRAT / Vendor Border",
    subtitle="Nokia↔Huawei and inter-RAT handover pain on the live Zain overlay.",
    kind="irat-border",
    api_url="/api/irat-border/issues",
    builder=irat_border,
    default_technology="all",
)
