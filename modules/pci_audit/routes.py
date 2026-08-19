from core.radio.blueprint import make_radio_module
from core.radio.pci_audit import pci_audit

pci_audit_bp = make_radio_module(
    name="pci_audit",
    href="/pci-audit",
    title="PCI Audit",
    subtitle="PCI collision and confusion across defined neighbour relations, plus mod3/mod30 interference risk on busy pairs.",
    kind="pci-audit",
    api_url="/api/pci-audit/issues",
    builder=pci_audit,
    default_technology="all",
    default_limit=300,
)
