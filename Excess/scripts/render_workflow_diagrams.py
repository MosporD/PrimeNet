"""
Extract Mermaid blocks from PRIMENET_WORKFLOW.md, render PNGs via mermaid-cli,
and rewrite the markdown with embedded diagram images.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD = PROJECT_ROOT / "PRIMENET_WORKFLOW.md"
MMD_DIR = PROJECT_ROOT / "docs" / "primenet_workflow" / "mermaid"
IMG_DIR = PROJECT_ROOT / "docs" / "primenet_workflow" / "images"
IMG_REL = "docs/primenet_workflow/images"


def _slug_from_heading(heading: str, index: int) -> str:
    text = heading.strip().lstrip("#").strip()
    text = re.sub(r"^\d+\.\s*", "", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text).strip("-").lower()
    text = text[:60] or f"diagram-{index:02d}"
    return f"{index:02d}-{text}"


def _strip_existing_embeds(md: str) -> str:
    """Remove image embeds and unwrap <details> back to plain mermaid fences."""

    def _details_to_mermaid(match: re.Match) -> str:
        body = match.group(1).strip()
        return f"\n```mermaid\n{body}\n```\n"

    md = re.sub(
        r"<details>\s*<summary>Edit Mermaid source</summary>\s*```mermaid\n([\s\S]*?)```\s*</details>",
        _details_to_mermaid,
        md,
    )
    md = re.sub(
        r"\n*!\[[^\]]*\]\(docs/primenet_workflow/images/[^)]+\)\s*",
        "\n",
        md,
    )
    md = re.sub(
        r"> \*\*Viewing:\*\*[\s\S]*?\n\n",
        "",
        md,
        count=1,
    )
    return md


def _extract_diagrams(md: str) -> list[tuple[str, str, str]]:
    """Return list of (slug, alt_text, mermaid_source)."""
    lines = md.splitlines()
    diagrams: list[tuple[str, str, str]] = []
    section_heading = "diagram"
    subsection_heading = ""
    idx = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            section_heading = line[3:].strip()
            subsection_heading = ""
        elif line.startswith("### "):
            subsection_heading = line[4:].strip()
        if line.strip() == "```mermaid":
            idx += 1
            label = subsection_heading or section_heading
            slug = _slug_from_heading(label, idx)
            alt = label
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            diagrams.append((slug, alt, "\n".join(body)))
        i += 1
    return diagrams


def _npx_executable() -> str:
    for name in ("npx.cmd", "npx.exe", "npx"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("npx not found on PATH; install Node.js")


def _render_png(mmd_path: Path, png_path: Path) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _npx_executable(),
        "--yes",
        "@mermaid-js/mermaid-cli@11.4.0",
        "-i",
        str(mmd_path),
        "-o",
        str(png_path),
        "-b",
        "white",
        "-w",
        "2400",
        "-H",
        "1600",
        "--scale",
        "2",
    ]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"mmdc failed for {mmd_path.name}:\n{proc.stderr or proc.stdout}"
        )


def _inject_images(md: str, diagrams: list[tuple[str, str, str]]) -> str:
    slug_iter = iter(diagrams)
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "```mermaid":
            slug, alt, source = next(slug_iter)
            img_rel = f"{IMG_REL}/{slug}.png"
            out.append("")
            out.append(f"![{alt}]({img_rel})")
            out.append("")
            out.append("<details>")
            out.append("<summary>Edit Mermaid source</summary>")
            out.append("")
            out.append("```mermaid")
            out.extend(source.splitlines())
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                i += 1
            out.append("```")
            out.append("")
            out.append("</details>")
            out.append("")
            if i < len(lines) and lines[i].strip() == "```":
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out) + "\n"


def main() -> int:
    if not SOURCE_MD.is_file():
        print(f"Missing {SOURCE_MD}", file=sys.stderr)
        return 1

    raw_md = SOURCE_MD.read_text(encoding="utf-8")
    clean_md = _strip_existing_embeds(raw_md)
    diagrams = _extract_diagrams(clean_md)
    if not diagrams:
        print("No mermaid diagrams found.", file=sys.stderr)
        return 1

    MMD_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Rendering {len(diagrams)} diagram(s)...")
    for slug, _alt, source in diagrams:
        mmd_path = MMD_DIR / f"{slug}.mmd"
        png_path = IMG_DIR / f"{slug}.png"
        mmd_path.write_text(source + "\n", encoding="utf-8")
        print(f"  {slug}.png ...", end=" ", flush=True)
        try:
            _render_png(mmd_path, png_path)
            print("OK")
        except Exception as e:
            print(f"FAIL\n    {e}")
            return 1

    note = (
        "> **Viewing:** Diagrams below are rendered PNG images (also in "
        f"`{IMG_REL}/`). Re-run `python scripts/render_workflow_diagrams.py` "
        "after editing Mermaid source inside the collapsible sections.\n\n"
    )
    new_md = _inject_images(clean_md, diagrams)
    if "**Viewing:**" not in new_md:
        new_md = re.sub(
            r"(\*\*Sources:\*\*[^\n]+\n\n)",
            r"\1" + note,
            new_md,
            count=1,
        )

    SOURCE_MD.write_text(new_md, encoding="utf-8")
    print(f"Updated {SOURCE_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
