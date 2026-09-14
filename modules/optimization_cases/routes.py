"""Optimization Cases — HTTP API + workspace page."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core.cases import selection, service, store
from core.cases.config import STATES, TRANSITIONS
from core.cases.schema import init_schema
from database_enhanced import get_user_by_session, log_activity

optimization_cases_bp = Blueprint(
    "optimization_cases",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/optimization-cases/static",
)


@optimization_cases_bp.before_request
def _guard_access():
    from core.module_access import module_access_before_request

    return module_access_before_request("/optimization-cases")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("session_token")
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def _user():
    token = request.cookies.get("session_token")
    return get_user_by_session(token) if token else None


def _username() -> str:
    user = getattr(request, "current_user", None) or _user()
    return str((user or {}).get("username") or "")


def _format_user(user):
    if not user:
        return None
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "role": user.get("role"),
    }


def _json_error(exc, code: int = 400):
    return jsonify({"success": False, "error": str(exc)}), code


@optimization_cases_bp.route("/optimization-cases")
@login_required
def page():
    try:
        init_schema()
    except Exception:
        pass
    return render_template(
        "optimization_cases.html",
        user=_format_user(getattr(request, "current_user", None) or _user()),
        states=list(STATES),
    )


@optimization_cases_bp.route("/api/optimization-cases/stats")
@login_required
def api_stats():
    try:
        init_schema()
        return jsonify({"success": True, "stats": store.case_stats(), "states": list(STATES)})
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases")
@login_required
def api_list():
    try:
        init_schema()
        state = (request.args.get("state") or "").strip()
        owner = (request.args.get("owner") or "").strip()
        search = (request.args.get("search") or "").strip()
        limit = int(request.args.get("limit") or 100)
        rows = store.list_cases(state=state, owner=owner, search=search, limit=limit)
        return jsonify({"success": True, "cases": rows, "stats": store.case_stats()})
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/<case_id>")
@login_required
def api_get(case_id: str):
    try:
        init_schema()
        case = store.get_case(case_id)
        if not case:
            return _json_error("Case not found", 404)
        events = store.list_events(case_id)
        allowed = sorted(TRANSITIONS.get(case.get("state") or "open", frozenset()))
        return jsonify({"success": True, "case": case, "events": events, "allowed_transitions": allowed})
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases", methods=["POST"])
@login_required
def api_create():
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        actor = _username()
        if body.get("issue"):
            case = service.open_case_from_issue(body["issue"], actor=actor)
        else:
            case = store.create_case(body, actor=actor)
            if body.get("refresh", True):
                case = service.refresh_case_evidence(case["case_id"], actor=actor)
        try:
            log_activity(actor, "optimization_case_create", f"case_id={case['case_id']}")
        except Exception:
            pass
        return jsonify({"success": True, "case": case})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/from-issue", methods=["POST"])
@login_required
def api_from_issue():
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        issue = body.get("issue") or body
        case = service.open_case_from_issue(issue, actor=_username())
        try:
            log_activity(_username(), "optimization_case_from_issue", f"case_id={case['case_id']}")
        except Exception:
            pass
        return jsonify({"success": True, "case": case, "case_url": f"/optimization-cases?case={case['case_id']}"})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/<case_id>", methods=["PATCH"])
@login_required
def api_patch(case_id: str):
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        case = store.update_case(case_id, body, actor=_username())
        return jsonify({"success": True, "case": case})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/<case_id>/transition", methods=["POST"])
@login_required
def api_transition(case_id: str):
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        case = store.transition_case(
            case_id,
            str(body.get("state") or ""),
            actor=_username(),
            note=str(body.get("note") or ""),
        )
        return jsonify({"success": True, "case": case})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/<case_id>/refresh-evidence", methods=["POST"])
@login_required
def api_refresh_evidence(case_id: str):
    try:
        init_schema()
        case = service.refresh_case_evidence(case_id, actor=_username())
        return jsonify({"success": True, "case": case})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/<case_id>/refresh-scorecard", methods=["POST"])
@login_required
def api_refresh_scorecard(case_id: str):
    try:
        init_schema()
        case = service.refresh_case_scorecard(case_id, actor=_username())
        return jsonify({"success": True, "case": case})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/selection-context", methods=["GET"])
@login_required
def api_selection_get():
    try:
        init_schema()
        return jsonify({"success": True, "selection": selection.get_selection(_username())})
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/selection-context", methods=["PUT", "POST"])
@login_required
def api_selection_set():
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        payload = body.get("selection") if isinstance(body.get("selection"), dict) else body
        saved = selection.set_selection(_username(), payload)
        return jsonify({"success": True, "selection": saved})
    except ValueError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/selection-context", methods=["DELETE"])
@login_required
def api_selection_clear():
    try:
        init_schema()
        saved = selection.clear_selection(_username())
        return jsonify({"success": True, "selection": saved})
    except Exception as exc:
        return _json_error(exc, 500)
