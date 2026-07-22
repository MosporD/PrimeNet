"""
Documentation module — renders the in-repo developer course
(``docs/course/*.md`` + ``docs/ARCHITECTURE.md``) as an admin-only page.

Admin-only: both the page and the content API are guarded by ``admin_required``.
Content is served only from a fixed catalog (no arbitrary file access).
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, render_template

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


def _catalog() -> list[dict]:
    """Ordered list of servable docs: Architecture overview, then course lessons."""
    items: list[dict] = []

    arch = os.path.join(_ROOT, "docs", "ARCHITECTURE.md")
    if os.path.isfile(arch):
        items.append({
            "id": "ARCHITECTURE",
            "path": arch,
            "group": "Overview",
            "title": "Architecture Overview",
        })

    if os.path.isdir(_COURSE_DIR):
        names = sorted(
            f for f in os.listdir(_COURSE_DIR) if f.endswith(".md")
        )
        # README first, then numbered lessons in order.
        names.sort(key=lambda f: (0 if f.lower() == "readme.md" else 1, f))
        for fname in names:
            path = os.path.join(_COURSE_DIR, fname)
            doc_id = fname[:-3]  # strip .md
            title = extract_title(_read(path)) or doc_id
            items.append({
                "id": doc_id,
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


@documentation_bp.route("/documentation")
@admin_required
def documentation_page():
    catalog = _catalog()
    nav = [
        {"id": item["id"], "title": item["title"], "group": item["group"]}
        for item in catalog
    ]
    default_id = catalog[0]["id"] if catalog else ""
    return render_template(
        "documentation.html",
        user=format_user(get_current_user()),
        nav=nav,
        default_id=default_id,
    )


@documentation_bp.route("/api/documentation/page/<doc_id>")
@admin_required
def documentation_content(doc_id: str):
    item = _catalog_by_id().get(doc_id)
    if not item:
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
