"""
Platform Admin (NexusCore) — identity, portal allow-list, and PrimeNet module access.
"""

from __future__ import annotations

from functools import wraps

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from core.platform.portal_access import (
    ALL_PORTAL_KEYS,
    catalog_for_admin,
    parse_allowed_portals,
    PORTAL_LABELS,
)
from core.platform.session import get_session_token
from core.table_excel_export import build_table_workbook
from database_enhanced import (
    count_active_admins,
    create_user,
    delete_user,
    get_all_users,
    get_user_by_session,
    log_activity,
    reset_user_password,
    set_user_force_password_change,
    update_user_portals as db_update_user_portals,
    update_user_role as db_update_user_role,
    update_user_status as db_update_user_status,
)
from sync_config import NCM_DEFAULT_USER_PASSWORD

platform_admin_bp = Blueprint(
    "platform_admin",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/platform_admin/static",
)

ROLE_LABELS = {
    "admin": "Owner",
    "user": "User",
    "ran_config_user": "RNC User",
    "noc_sys": "NOC SYS",
}


def _user_role(user) -> str:
    if not user:
        return ""
    raw = user.get("role") if isinstance(user, dict) else user[6]
    return str(raw or "").strip().lower()


def _is_owner(user) -> bool:
    return _user_role(user) == "admin"


def _can_access_user_admin(user) -> bool:
    return _user_role(user) in {"admin", "noc_sys"}


def _format_user_data(user):
    if not user:
        return None
    if isinstance(user, dict):
        return {
            "username": user.get("username"),
            "email": user.get("email"),
            "role": user.get("role"),
            "id": user.get("id"),
        }
    return {
        "username": user[1],
        "email": user[2],
        "role": user[6],
        "id": user[0],
    }


def get_current_user():
    session_token = get_session_token()
    if session_token:
        return get_user_by_session(session_token)
    return None


def platform_admin_required(f):
    """Owner or NOC SYS — page + user APIs."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = get_session_token()
        if not session_token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(session_token)
        if not _can_access_user_admin(user):
            return redirect(url_for("nexuscore.portal_select"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated_function


@platform_admin_bp.route("/admin")
@platform_admin_required
def platform_admin_page():
    user = get_current_user()
    role = _user_role(user)
    return render_template(
        "platform_admin.html",
        user=_format_user_data(user),
        role_labels=ROLE_LABELS,
        can_manage_access=role == "admin",
        default_user_password=NCM_DEFAULT_USER_PASSWORD,
    )


@platform_admin_bp.route("/api/platform-admin/feature-access", methods=["GET"])
def get_feature_access():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({"error": "Owner access required"}), 403
    from core import feature_access
    from core.module_access import feature_catalog

    return jsonify(
        {
            "success": True,
            "editable_roles": [
                {"key": r, "label": feature_access.ROLE_LABELS.get(r, r)}
                for r in feature_access.EDITABLE_ROLES
            ],
            "features": feature_catalog(),
        }
    )


@platform_admin_bp.route("/api/platform-admin/feature-access", methods=["POST"])
def update_feature_access():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({"error": "Owner access required"}), 403
    from core import feature_access
    from core.module_access import feature_catalog

    data = request.get_json(silent=True) or {}
    updates = data.get("updates")
    if not isinstance(updates, list):
        return jsonify({"error": 'Expected {"updates": [...]}'}), 400

    known = {f["href"]: f for f in feature_catalog()}
    valid_roles = set(feature_access.EDITABLE_ROLES)
    applied = 0
    for item in updates:
        if not isinstance(item, dict):
            continue
        href = str(item.get("href") or "").strip()
        feat = known.get(href)
        if not feat or feat.get("locked"):
            continue
        roles = [str(r).strip().lower() for r in (item.get("roles") or [])]
        roles = [r for r in roles if r in valid_roles]
        feature_access.set_feature_roles(
            href,
            roles,
            updated_by=str(user.get("username") if isinstance(user, dict) else user[1]),
        )
        applied += 1

    log_activity(
        (user.get("id") if isinstance(user, dict) else user[0]),
        "admin_feature_access_update",
        f"Updated visibility for {applied} feature(s)",
    )
    return jsonify({"success": True, "updated": applied, "features": feature_catalog()})


@platform_admin_bp.route("/api/platform-admin/feature-access/reset", methods=["POST"])
def reset_feature_access():
    user = get_current_user()
    if not _is_owner(user):
        return jsonify({"error": "Owner access required"}), 403
    from core import feature_access
    from core.module_access import feature_catalog

    feature_access.reset_all()
    log_activity(
        (user.get("id") if isinstance(user, dict) else user[0]),
        "admin_feature_access_reset",
        "Reset all feature visibility to defaults",
    )
    return jsonify({"success": True, "features": feature_catalog()})


@platform_admin_bp.route("/api/platform-admin/users", methods=["GET"])
def get_users():
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({"error": "Owner or NOC SYS access required"}), 403

    try:
        users = get_all_users()
        users_data = []
        for u in users:
            portals = list(u.get("allowed_portals") or [])
            users_data.append(
                {
                    "id": u["id"],
                    "username": u["username"],
                    "email": u["email"],
                    "created_at": u["created_at"],
                    "is_active": bool(u["is_active"]),
                    "role": u["role"],
                    "role_label": ROLE_LABELS.get(
                        str(u.get("role", "")).strip().lower(), u.get("role", "")
                    ),
                    "last_activity": u["last_login"],
                    "allowed_portals": portals,
                    "portal_labels": [PORTAL_LABELS.get(p, p) for p in portals],
                }
            )

        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "admin_view_users",
            "Viewed user list",
        )
        return jsonify(
            {
                "success": True,
                "users": users_data,
                "portal_catalog": catalog_for_admin(),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@platform_admin_bp.route("/api/platform-admin/users", methods=["POST"])
def create_user_account():
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({"error": "Owner or NOC SYS access required"}), 403

    try:
        data = request.get_json() or {}
        username = str(data.get("username") or "").strip()
        email = str(data.get("email") or "").strip()
        full_name = str(data.get("full_name") or "").strip() or None
        department = str(data.get("department") or "").strip() or None
        role = str(data.get("role") or "user").strip().lower()
        use_default_password = bool(data.get("use_default_password", True))
        custom_password = str(data.get("password") or "").strip()
        raw_portals = data.get("allowed_portals")
        if raw_portals is None:
            portals = None
        else:
            portals = parse_allowed_portals(raw_portals, role=role)

        if not username:
            return jsonify({"error": "Username is required"}), 400
        if not email or "@" not in email:
            return jsonify({"error": "A valid email is required"}), 400
        if role not in ROLE_LABELS:
            return jsonify({"error": "Invalid role"}), 400
        if portals is not None and not portals:
            return jsonify({"error": "Select at least one portal"}), 400

        if use_default_password:
            password = NCM_DEFAULT_USER_PASSWORD
            force_change = False
        else:
            password = custom_password
            if len(password) < 8:
                return jsonify({"error": "Password must be at least 8 characters"}), 400
            force_change = bool(data.get("force_password_change", False))

        if not password:
            return jsonify({"error": "Password is required"}), 400

        success, result = create_user(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            department=department,
            role=role,
            allowed_portals=portals,
        )
        if not success:
            return jsonify({"error": result}), 400

        user_id = int(result)
        set_user_force_password_change(user_id, force_change)

        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "admin_create_user",
            f"Created user {username} ({user_id})",
        )
        return jsonify(
            {
                "success": True,
                "message": f"User {username} created",
                "user_id": user_id,
                "used_default_password": use_default_password,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@platform_admin_bp.route("/api/platform-admin/users/<int:user_id>/reset-password", methods=["POST"])
def reset_user_password_to_default(user_id):
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({"error": "Owner or NOC SYS access required"}), 403

    try:
        if not NCM_DEFAULT_USER_PASSWORD:
            return jsonify({"error": "Default user password is not configured"}), 500

        if not reset_user_password(
            user_id,
            NCM_DEFAULT_USER_PASSWORD,
            force_password_change=False,
        ):
            return jsonify({"error": "User not found"}), 404

        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "admin_reset_password",
            f"Reset password to default for user {user_id}",
        )
        return jsonify({"success": True, "message": "Password reset to default"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@platform_admin_bp.route("/api/platform-admin/users/<int:user_id>/portals", methods=["PUT"])
def update_user_portals(user_id):
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({"error": "Owner or NOC SYS access required"}), 403

    try:
        data = request.get_json() or {}
        portals = parse_allowed_portals(data.get("allowed_portals") or data.get("portals") or [])
        if not portals:
            return jsonify({"error": "Select at least one portal"}), 400
        unknown = [p for p in portals if p not in ALL_PORTAL_KEYS]
        if unknown:
            return jsonify({"error": f'Unknown portal(s): {", ".join(unknown)}'}), 400

        if not db_update_user_portals(user_id, portals):
            return jsonify({"error": "User not found"}), 404

        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "admin_change_portals",
            f'Changed user {user_id} portals to {",".join(portals)}',
        )
        return jsonify(
            {
                "success": True,
                "message": "Portal access updated",
                "allowed_portals": portals,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@platform_admin_bp.route("/api/platform-admin/users/<int:user_id>/role", methods=["PUT"])
def update_user_role(user_id):
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({"error": "Owner or NOC SYS access required"}), 403

    try:
        data = request.get_json()
        new_role = data.get("role")

        if new_role not in ["admin", "user", "ran_config_user", "noc_sys"]:
            return jsonify({"error": "Invalid role"}), 400

        if not db_update_user_role(user_id, new_role):
            return jsonify({"error": "User not found"}), 404

        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "admin_change_role",
            f"Changed user {user_id} role to {new_role}",
        )
        return jsonify({"success": True, "message": f"Role updated to {new_role}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@platform_admin_bp.route("/api/platform-admin/users/<int:user_id>", methods=["DELETE"])
def remove_user_account(user_id):
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({"error": "Owner or NOC SYS access required"}), 403

    try:
        actor_id = user.get("id") if isinstance(user, dict) else user[0]
        if int(user_id) == int(actor_id):
            return jsonify({"error": "You cannot delete your own account"}), 400

        target_users = [u for u in get_all_users() if int(u["id"]) == int(user_id)]
        if not target_users:
            return jsonify({"error": "User not found"}), 404

        target = target_users[0]
        if str(target.get("role", "")).strip().lower() == "admin" and bool(target.get("is_active")):
            if count_active_admins(exclude_user_id=user_id) < 1:
                return jsonify({"error": "Cannot delete the last active owner account"}), 400

        success, result = delete_user(user_id)
        if not success:
            if result == "User not found":
                return jsonify({"error": result}), 404
            return jsonify({"error": result}), 500

        log_activity(
            actor_id,
            "admin_delete_user",
            f"Deleted user {result} ({user_id})",
        )
        return jsonify({"success": True, "message": f"User {result} removed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@platform_admin_bp.route("/api/platform-admin/users/<int:user_id>/status", methods=["PUT"])
def update_user_status(user_id):
    user = get_current_user()
    if not _can_access_user_admin(user):
        return jsonify({"error": "Owner or NOC SYS access required"}), 403

    try:
        data = request.get_json()
        is_active = data.get("is_active")

        if is_active is None:
            return jsonify({"error": "is_active required"}), 400

        if not db_update_user_status(user_id, int(is_active)):
            return jsonify({"error": "User not found"}), 404

        status_text = "activated" if is_active else "deactivated"
        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "admin_change_status",
            f"User {user_id} {status_text}",
        )
        return jsonify({"success": True, "message": f"User {status_text}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@platform_admin_bp.route("/api/platform-admin/export/excel", methods=["POST"])
@platform_admin_required
def admin_export_excel():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    table_key = str(data.get("table") or "").strip().lower()
    columns = [str(c) for c in (data.get("columns") or []) if str(c).strip()]
    rows = data.get("rows")
    if table_key != "users":
        return jsonify({"error": "Unknown export table"}), 400
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "No rows to export"}), 400

    report_title = str(data.get("report_title") or "User Administration")
    sheet_title = str(data.get("sheet_title") or report_title)[:31]
    filename_stem = str(data.get("filename_stem") or "Platform_Users")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    column_labels = data.get("column_labels") if isinstance(data.get("column_labels"), dict) else {}

    try:
        workbook, filename = build_table_workbook(
            filename_stem=filename_stem,
            report_title=report_title,
            sheet_title=sheet_title,
            columns=columns,
            rows=rows,
            column_labels=column_labels,
            meta={
                **meta,
                "Exported By": (user.get("username") if isinstance(user, dict) else user[1]),
                "Row Count": len(rows),
            },
        )
        log_activity(
            (user.get("id") if isinstance(user, dict) else user[0]),
            "admin_table_export",
            f"Exported {table_key} ({len(rows)} rows)",
        )
        return send_file(
            workbook,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
