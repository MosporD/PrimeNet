"""Optimization Cases — HTTP API + workspace page."""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from core.cases import selection, service, store
from core.cases.config import STATES, TRANSITIONS
from core.cases.schema import init_schema
from database_enhanced import get_user_by_session, log_activity
from core.platform.session import get_session_token

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
        token = get_session_token()
        if not token:
            return redirect(url_for("auth.login_page"))
        user = get_user_by_session(token)
        if not user:
            return redirect(url_for("auth.login_page"))
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def _user():
    token = get_session_token()
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


# Static path routes MUST come before /<case_id>
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


@optimization_cases_bp.route("/api/optimization-cases/from-morning-report", methods=["POST"])
@login_required
def api_from_morning_report():
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        issues = body.get("issues")
        if issues is None:
            from core.radio.insights import radio_morning_report

            area = str(body.get("area") or "all")
            vendor = str(body.get("vendor") or "all")
            technology = str(body.get("technology") or "all")
            limit = int(body.get("limit") or 100)
            payload = radio_morning_report(area=area, vendor=vendor, technology=technology, limit=limit)
            issues = payload.get("issues") or []
        result = service.open_cases_from_morning_report(
            issues,
            actor=_username(),
            severities=tuple(body.get("severities") or ("Critical", "High")),
            limit=int(body.get("max_cases") or 25),
            dedupe_days=int(body.get("dedupe_days") or 7),
        )
        try:
            log_activity(
                _username(),
                "optimization_cases_morning_report",
                f"created={result.get('created_count')} skipped={result.get('skipped_count')}",
            )
        except Exception:
            pass
        return jsonify({"success": True, **result})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/complaint", methods=["POST"])
@login_required
def api_complaint():
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        cells = body.get("cells") or []
        if isinstance(cells, str):
            cells = [c.strip() for c in cells.replace(";", ",").split(",") if c.strip()]
        case = service.create_complaint_case(
            ticket_id=str(body.get("ticket_id") or ""),
            site_id=str(body.get("site_id") or ""),
            postcode=str(body.get("postcode") or ""),
            cells=cells,
            summary=str(body.get("summary") or ""),
            actor=_username(),
        )
        return jsonify({"success": True, "case": case, "case_url": f"/optimization-cases?case={case['case_id']}"})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/energy", methods=["POST"])
@login_required
def api_energy():
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        issue = body.get("issue") or body
        case = service.open_energy_case(issue, actor=_username())
        return jsonify({"success": True, "case": case, "case_url": f"/optimization-cases?case={case['case_id']}"})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/cluster-acceptance", methods=["POST"])
@login_required
def api_cluster_acceptance():
    try:
        init_schema()
        body = request.get_json(silent=True) or {}
        cells = body.get("cells") or []
        if isinstance(cells, str):
            cells = [c.strip() for c in cells.replace(";", ",").split(",") if c.strip()]
        issue = {
            "title": body.get("title") or "Cluster acceptance",
            "summary": body.get("summary") or "Cluster acceptance checklist case",
            "category": "Cluster Acceptance",
            "case_type": "cluster_acceptance",
            "module": "Cluster Acceptance",
            "severity": body.get("severity") or "Medium",
            "score": body.get("score") or 50,
            "cells": cells,
            "site_id": body.get("site_id") or "",
            "vendor": body.get("vendor") or "",
            "technology": body.get("technology") or "",
            "checklist": body.get("checklist") or {},
            "source_url": "/optimization-cases",
        }
        case = service.open_case_from_issue(issue, actor=_username())
        return jsonify({"success": True, "case": case})
    except store.CaseError as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/treatments")
@login_required
def api_treatments():
    try:
        from core.cases import treatments

        init_schema()
        rows = treatments.list_trusted(min_improve=int(request.args.get("min_improve") or 3))
        return jsonify({"success": True, "treatments": rows})
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
        related = store.find_related_by_cells(
            case.get("cells") or [],
            exclude_case_id=case_id,
            within_days=30,
        )
        pm_link = service.pm_deeplink_for_case(case)
        return jsonify(
            {
                "success": True,
                "case": case,
                "events": events,
                "allowed_transitions": allowed,
                "related_cases": related,
                "pm_deeplink": pm_link,
            }
        )
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
            override_note=str(body.get("override_note") or ""),
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


@optimization_cases_bp.route("/api/optimization-cases/<case_id>/related")
@login_required
def api_related(case_id: str):
    try:
        init_schema()
        case = store.get_case(case_id)
        if not case:
            return _json_error("Case not found", 404)
        related = store.find_related_by_cells(
            case.get("cells") or [],
            exclude_case_id=case_id,
            within_days=int(request.args.get("days") or 30),
        )
        return jsonify({"success": True, "related_cases": related})
    except Exception as exc:
        return _json_error(exc, 500)


@optimization_cases_bp.route("/api/optimization-cases/<case_id>/pm-deeplink")
@login_required
def api_pm_deeplink(case_id: str):
    try:
        init_schema()
        case = store.get_case(case_id)
        if not case:
            return _json_error("Case not found", 404)
        return jsonify({"success": True, "deeplink": service.pm_deeplink_for_case(case)})
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
