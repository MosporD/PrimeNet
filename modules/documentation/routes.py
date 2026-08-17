"""
Documentation module — architecture, in-repo course, and graphify maps.

Admin-only. Markdown is served from a fixed catalog (no arbitrary file access).
Graphify HTML maps are served from ``graphify-out/`` by whitelist only.
"""

from __future__ import annotations

import os

from flask import Blueprint, abort, jsonify, render_template, send_from_directory

from core.radio.web import admin_required, format_user, get_current_user

from .md import extract_title, render_markdown

documentation_bp = Blueprint(
    "documentation",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/documentation/static",
)

# Project root = three levels up from this file.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_COURSE_DIR = os.path.join(_ROOT, "docs", "course")
_MAP_DIR = os.path.join(_ROOT, "graphify-out")

# Whitelist only — never interpolate user input into a filesystem path.
_MAPS: tuple[dict, ...] = (
    {
        "id": "graph",
        "group": "Overview",
        "title": "Graph",
        "file": "graph.html",
        "missing": (
            "Interactive graph is not generated yet. From the repo root run:\n"
            "python -m graphify update ."
        ),
    },
    {
        "id": "code-map",
        "group": "Overview",
        "title": "Code map",
        "file": "GRAPH_TREE.html",
        "missing": (
            "Code map is not generated yet. From the repo root run:\n"
            "python -m graphify tree --label PrimeNet"
        ),
    },
    {
        "id": "call-flow",
        "group": "Overview",
        "title": "Call flow",
        "file": "Project-callflow.html",
        "missing": (
            "Call-flow map is not generated yet. From the repo root run:\n"
            "python -m graphify export callflow-html"
        ),
    },
)


def _catalog() -> list[dict]:
    """Architecture, graphify maps, then course lessons."""
    items: list[dict] = []

    arch = os.path.join(_ROOT, "docs", "ARCHITECTURE.md")
    if os.path.isfile(arch):
        items.append({
            "id": "ARCHITECTURE",
            "kind": "md",
            "path": arch,
            "group": "Overview",
            "title": "Architecture Overview",
        })

    for spec in _MAPS:
        items.append({
            "id": spec["id"],
            "kind": "map",
            "group": spec["group"],
            "title": spec["title"],
            "file": spec["file"],
        })

    if os.path.isdir(_COURSE_DIR):
        names = sorted(
            f for f in os.listdir(_COURSE_DIR)
            if f.endswith(".md") and f.lower() != "12-graphify.md"
        )
        names.sort(key=lambda f: (0 if f.lower() == "readme.md" else 1, f))
        for fname in names:
            path = os.path.join(_COURSE_DIR, fname)
            doc_id = fname[:-3]
            title = extract_title(_read(path)) or doc_id
            items.append({
                "id": doc_id,
                "kind": "md",
                "path": path,
                "group": "Course",
                "title": title,
            })
    return items


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _catalog_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in _catalog()}


def _map_spec(map_id: str) -> dict | None:
    for spec in _MAPS:
        if spec["id"] == map_id:
            return spec
    return None


@documentation_bp.route("/documentation")
@admin_required
def documentation_page():
    catalog = _catalog()
    nav = [
        {
            "id": item["id"],
            "title": item["title"],
            "group": item["group"],
            "kind": item.get("kind") or "md",
        }
        for item in catalog
    ]
    default_id = catalog[0]["id"] if catalog else ""
    return render_template(
        "documentation.html",
        user=format_user(get_current_user()),
        nav=nav,
        default_id=default_id,
    )


@documentation_bp.route("/documentation/map/<map_id>")
@admin_required
def documentation_map(map_id: str):
    spec = _map_spec(map_id)
    if not spec:
        abort(404)
    filename = spec["file"]
    path = os.path.join(_MAP_DIR, filename)
    if not os.path.isfile(path):
        body = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Map missing</title>"
            "<style>body{font-family:Segoe UI,sans-serif;padding:32px;color:#1f2733}"
            "pre{background:#f0f3f9;padding:12px 16px;border-radius:8px}</style></head><body>"
            f"<h1>{spec['title']} is not on disk</h1>"
            f"<pre>{spec['missing']}</pre></body></html>"
        )
        return body, 404, {"Content-Type": "text/html; charset=utf-8"}
    return send_from_directory(_MAP_DIR, filename)


@documentation_bp.route("/api/documentation/page/<doc_id>")
@admin_required
def documentation_content(doc_id: str):
    item = _catalog_by_id().get(doc_id)
    if not item or item.get("kind") == "map":
        return jsonify({"success": False, "error": "Unknown document."}), 404
    text = _read(item["path"])
    if not text:
        return jsonify({"success": False, "error": "Document is empty or unreadable."}), 404
    return jsonify({
        "success": True,
        "id": doc_id,
        "title": extract_title(text) or item["title"],
        "html": render_markdown(text),
    })
