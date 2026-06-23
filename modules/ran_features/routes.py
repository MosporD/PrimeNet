"""RAN Features module — serves Huawei compiled HDX documentation."""

import os

from flask import Blueprint, render_template, request, redirect, url_for, abort, Response, jsonify
from functools import wraps

from database_enhanced import get_user_by_session
from .hdx import HDX_DIR, TECH_FILES, get_home_page, read_file, guess_mimetype
from .navi import get_navi_payload

ran_features_bp = Blueprint(
    "ran_features",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/ran-features/static",
)


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


def _current_user():
    token = request.cookies.get("session_token")
    return get_user_by_session(token) if token else None


def _fmt_user(user):
    if not user:
        return None
    return {"id": user.get("id"), "username": user.get("username"), "role": user.get("role")}


@ran_features_bp.route("/ran-features")
@login_required
def ran_features_page():
    user = _current_user()
    techs = []
    for key, info in TECH_FILES.items():
        path = os.path.join(HDX_DIR, info["file"])
        size_mb = round(os.path.getsize(path) / (1024 * 1024), 1) if os.path.isfile(path) else None
        techs.append({"key": key, "label": info["label"], "available": size_mb is not None, "size_mb": size_mb})
    return render_template("ran_features.html", user=_fmt_user(user), techs=techs)


@ran_features_bp.route("/api/ran-features/toc/<tech>")
def ran_features_toc(tech):
    user = _current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    tech = tech.lower().strip()
    if tech not in TECH_FILES:
        return jsonify({"error": "Not found"}), 404
    hdx_path = os.path.join(HDX_DIR, TECH_FILES[tech]["file"])
    if not os.path.isfile(hdx_path):
        return jsonify({"error": "Documentation not available"}), 404
    payload = get_navi_payload(tech)
    return jsonify({"success": True, "tech": tech, **payload})


@ran_features_bp.route("/ran-features/open/<tech>")
@login_required
def ran_features_open(tech):
    return redirect(f"/ran-features?vendor=huawei&view={tech.lower().strip()}")


@ran_features_bp.route("/ran-features/view/<tech>/")
@ran_features_bp.route("/ran-features/view/<tech>/<path:filepath>")
@login_required
def ran_features_view(tech, filepath=None):
    tech = tech.lower().strip()
    entry = TECH_FILES.get(tech)
    if not entry:
        abort(404)
    hdx_path = os.path.join(HDX_DIR, entry["file"])
    if not os.path.isfile(hdx_path):
        abort(404)

    if not filepath:
        home = get_home_page(tech)
        if not home:
            abort(404)
        return redirect(f"/ran-features/view/{tech}/{home}")

    data = read_file(tech, filepath)
    if data is None:
        abort(404)

    mimetype = guess_mimetype(filepath)
    if mimetype.startswith("text/") or mimetype in ("application/javascript", "application/xml"):
        mimetype = f"{mimetype}; charset=utf-8"
    return Response(data, mimetype=mimetype)
