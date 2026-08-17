"""Push Nokia Load Balancing RAML plan to NetAct OSS (CM Operations actualImport)."""

from __future__ import annotations

import os
from typing import Any

from core.cm_extractor.config import build_nokia_operations_client
from core.cm_extractor.nokia_excel_reimport import _upload_to_omc

from .export import build_changes_xml
from .logic import load_preview, preview_xml, write_preview_xml


def apply_preview_to_oss(
    username: str,
    token: str,
    *,
    wait: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    preview = load_preview(username, token)
    changes = preview.get("changes") or []
    if not changes:
        raise ValueError("No parameter changes in preview.")

    xml_text = preview_xml(username, token)
    xml_path = write_preview_xml(username, token, xml_text)
    if dry_run:
        return {
            "dry_run": True,
            "xml_path": xml_path,
            "xml_bytes": len(xml_text.encode("utf-8")),
            "change_count": len(changes),
            "uploaded": False,
        }
    remote_name = f"primenet_nokia_lb_{token[:12]}.xml"
    remote_path = _upload_to_omc(xml_path, remote_name)

    operation_name = os.environ.get("NOKIA_CM_REIMPORT_OPERATION_NAME", "Import_Export")
    attributes = {
        "importExportOperation": os.environ.get("NOKIA_CM_REIMPORT_OPERATION_MODE", "actualImport"),
        "fileFormat": os.environ.get("NOKIA_CM_REIMPORT_FILE_FORMAT", "RAML2"),
        "fileName": remote_name,
        "inputFile": remote_path,
        "DN": os.environ.get("NOKIA_CM_REIMPORT_DN", "PLMN-PLMN"),
        "useQualifiedClassAbbreviation": os.environ.get("NOKIA_CM_REIMPORT_QUALIFIED_CLASS", "true"),
    }
    client = build_nokia_operations_client()
    operation_id = client.start_operation(
        operation_name,
        operation_alias=f"PrimeNet Nokia Load Balancing {token[:8]}",
        attributes={k: str(v) for k, v in attributes.items() if str(v).strip()},
    )
    result: dict[str, Any] = {
        "operation_id": operation_id,
        "operation_name": operation_name,
        "remote_path": remote_path,
        "change_count": len(changes),
    }
    if wait:
        status, feedbacks = client.wait_for_operation(operation_id, timeout_sec=900)
        result["status"] = status
        result["feedbacks"] = feedbacks[:50]
    return result
