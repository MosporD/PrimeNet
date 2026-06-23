from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_MD = PROJECT_ROOT / "PROJECT_DOCUMENTATION.md"
DEFAULT_OUTPUT_PDF = PROJECT_ROOT / "PROJECT_INFRASTRUCTURE_DOCUMENTATION.pdf"


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=styles["Title"],
            fontSize=20,
            leading=24,
            spaceAfter=14,
            textColor=colors.HexColor("#0f172a"),
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=styles["Heading2"],
            fontSize=14,
            leading=18,
            spaceBefore=10,
            spaceAfter=8,
            textColor=colors.HexColor("#0f172a"),
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=styles["Heading3"],
            fontSize=12,
            leading=16,
            spaceBefore=8,
            spaceAfter=6,
            textColor=colors.HexColor("#1e293b"),
        ),
        "body": ParagraphStyle(
            "Body",
            parent=styles["BodyText"],
            fontSize=10,
            leading=14,
            spaceAfter=6,
            textColor=colors.HexColor("#111827"),
        ),
        "code": ParagraphStyle(
            "Code",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=11,
            leftIndent=10,
            rightIndent=10,
            spaceAfter=8,
            backColor=colors.HexColor("#f3f4f6"),
        ),
    }


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\t", "    ")
    )


def markdown_to_story(md_text: str):
    s = _styles()
    story = []
    in_code_block = False
    code_lines: list[str] = []
    bullet_buffer: list[str] = []

    def flush_bullets():
        nonlocal bullet_buffer
        if not bullet_buffer:
            return
        items = [
            ListItem(Paragraph(_escape(line), s["body"]), leftIndent=12)
            for line in bullet_buffer
        ]
        story.append(ListFlowable(items, bulletType="bullet", start="circle", leftIndent=14))
        story.append(Spacer(1, 3))
        bullet_buffer = []

    def flush_code():
        nonlocal code_lines
        if not code_lines:
            return
        story.append(Preformatted("\n".join(code_lines), s["code"]))
        code_lines = []

    for raw in md_text.splitlines():
        line = raw.rstrip("\n")

        if line.strip().startswith("```"):
            flush_bullets()
            if not in_code_block:
                in_code_block = True
                code_lines = []
            else:
                in_code_block = False
                flush_code()
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_bullets()
            story.append(Spacer(1, 4))
            continue

        if line.startswith("# "):
            flush_bullets()
            story.append(Paragraph(_escape(line[2:].strip()), s["title"]))
            continue
        if line.startswith("## "):
            flush_bullets()
            story.append(Paragraph(_escape(line[3:].strip()), s["h2"]))
            continue
        if line.startswith("### "):
            flush_bullets()
            story.append(Paragraph(_escape(line[4:].strip()), s["h3"]))
            continue

        if line.lstrip().startswith("- "):
            bullet_buffer.append(line.lstrip()[2:].strip())
            continue

        flush_bullets()
        story.append(Paragraph(_escape(line), s["body"]))

    flush_bullets()
    if in_code_block:
        flush_code()

    return story


def build_pdf(source_md: Path, output_pdf: Path, title: str) -> None:
    if not source_md.exists():
        raise FileNotFoundError(f"Source file not found: {source_md}")

    content = source_md.read_text(encoding="utf-8")
    story = markdown_to_story(content)

    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title=title,
        author="PrimeNet",
    )
    doc.build(story)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PDF from a markdown documentation file.")
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE_MD),
        help="Path to source markdown file.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PDF),
        help="Path to output PDF file.",
    )
    parser.add_argument(
        "--title",
        default="PrimeNet Infrastructure Documentation",
        help="PDF document title metadata.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    build_pdf(source, output, args.title)
    print(f"PDF generated: {output}")
