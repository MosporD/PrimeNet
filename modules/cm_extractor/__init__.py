"""
CM Extractor Flask module — Nokia NetAct / Huawei U2020 configuration export.

CLI utilities live in ``modules.cm_extractor.scripts``:

- ``run_nokia_netact_discovery`` — refresh NetAct MRBTS/RNC/BSC inventory cache
- ``run_huawei_u2020_discovery`` — refresh U2020 NE / MO discovery cache
- ``run_huawei_rebuild_dictionary`` — rebuild Huawei parameter dictionary JSON
- ``run_due_jobs`` — execute due CM Extractor scheduled jobs once
- ``run_extraction`` — run Open API / bulk extraction from a JSON payload file
"""

from modules.cm_extractor.routes import cm_extractor_bp

__all__ = ['cm_extractor_bp']
