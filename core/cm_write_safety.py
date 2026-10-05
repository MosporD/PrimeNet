"""Shared CM live-write safety: preview tokens, caps, before-snapshots, audit."""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CmWriteSafetyError(ValueError):
    """Raised when a write gate fails (missing preview, over cap, expired)."""


def max_cells_per_push() -> int:
    raw = (os.getenv("NCM_CM_MAX_CELLS_PER_PUSH") or "50").strip()
    try:
        return max(1, min(5000, int(raw)))
    except ValueError:
        return 50


def preview_ttl_sec() -> int:
    raw = (os.getenv("NCM_CM_PREVIEW_TTL_MIN") or "60").strip()
    try:
        return max(60, int(float(raw) * 60))
    except ValueError:
        return 3600


def _root() -> Path:
    try:
        from sync_config import DATA_ROOT

        base = Path(DATA_ROOT)
    except Exception:
        base = Path(__file__).resolve().parents[1]
    path = base / "var" / "cm_write_previews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _preview_path(preview_id: str) -> Path:
    safe = "".join(c for c in preview_id if c.isalnum() or c in "-_")
    if not safe or safe != preview_id:
        raise CmWriteSafetyError("Invalid preview_id.")
    return _root() / f"{safe}.json"


def create_preview(
    *,
    module: str,
    username: str,
    changes: list[dict[str, Any]],
    before_snapshot: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a preview token. ``changes`` length is the unit counted toward the cap."""
    n = len(changes or [])
    assert_change_cap(n)
    preview_id = secrets.token_urlsafe(16)
    now = time.time()
    payload = {
        "preview_id": preview_id,
        "module": module,
        "username": username,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": now + preview_ttl_sec(),
        "change_count": n,
        "changes": changes,
        "before_snapshot": before_snapshot or {},
        "meta": meta or {},
        "consumed": False,
    }
    path = _preview_path(preview_id)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    if before_snapshot:
        store_before_snapshot(
            kind=module,
            user=username,
            targets={"preview_id": preview_id, "change_count": n},
            blob=before_snapshot,
            preview_id=preview_id,
        )
    return {
        "preview_id": preview_id,
        "change_count": n,
        "max_cells": max_cells_per_push(),
        "expires_in_sec": preview_ttl_sec(),
        "diff": changes,
    }


def require_preview_token(
    preview_id: str,
    *,
    module: str | None = None,
    username: str | None = None,
    consume: bool = True,
) -> dict[str, Any]:
    if not preview_id or not str(preview_id).strip():
        raise CmWriteSafetyError("preview_id is required. Run preview first.")
    path = _preview_path(str(preview_id).strip())
    if not path.is_file():
        raise CmWriteSafetyError("Preview not found or expired.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CmWriteSafetyError(f"Corrupt preview: {exc}") from exc
    if data.get("consumed"):
        raise CmWriteSafetyError("Preview already consumed.")
    if float(data.get("expires_at") or 0) < time.time():
        raise CmWriteSafetyError("Preview expired. Generate a new preview.")
    if module and str(data.get("module") or "") != module:
        raise CmWriteSafetyError("Preview module mismatch.")
    if username and str(data.get("username") or "") != username:
        raise CmWriteSafetyError("Preview belongs to a different user.")
    assert_change_cap(int(data.get("change_count") or len(data.get("changes") or [])))
    if consume:
        data["consumed"] = True
        data["consumed_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data


def assert_change_cap(n: int, max_n: int | None = None) -> None:
    limit = max_cells_per_push() if max_n is None else max(1, int(max_n))
    count = int(n or 0)
    if count <= 0:
        raise CmWriteSafetyError("No changes to apply.")
    if count > limit:
        raise CmWriteSafetyError(
            f"{count} changes exceeds max allowed per push ({limit}). "
            "Reduce the selection or raise NCM_CM_MAX_CELLS_PER_PUSH."
        )


def store_before_snapshot(
    *,
    kind: str,
    user: str,
    targets: dict[str, Any],
    blob: Any,
    preview_id: str | None = None,
) -> Path:
    try:
        from sync_config import DATA_ROOT

        base = Path(DATA_ROOT)
    except Exception:
        base = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_kind = "".join(c for c in kind if c.isalnum() or c in "-_") or "cm"
    folder = base / "var" / "cm_before_snapshots" / safe_kind
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{stamp}_{preview_id or 'nosnap'}_{user[:32]}.json"
    path = folder / name
    path.write_text(
        json.dumps(
            {
                "kind": kind,
                "user": user,
                "preview_id": preview_id,
                "targets": targets,
                "blob": blob,
                "stored_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def audit_write(
    user_id: int | str | None,
    module: str,
    action: str,
    summary: str,
    *,
    preview_id: str | None = None,
    cell_count: int | None = None,
) -> None:
    try:
        from database_enhanced import log_activity

        detail = summary
        if preview_id:
            detail = f"{detail} [preview_id={preview_id}]"
        if cell_count is not None:
            detail = f"{detail} [cells={cell_count}]"
        log_activity(user_id, module, detail)
    except Exception:
        pass
