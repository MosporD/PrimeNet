"""
Minimal, dependency-free Markdown -> HTML renderer.

Scoped to the constructs used by the PrimeNet course docs under ``docs/course``:
ATX headings, fenced code blocks, GFM pipe tables, unordered/ordered lists,
blockquotes, horizontal rules, paragraphs, and the inline spans
``code``/**bold**/*italic*/[links](url). Output is escaped for safety; only the
tags this renderer emits are ever produced.

This is intentionally small and predictable rather than a full CommonMark
implementation — the input is our own trusted documentation, not user content.
"""

from __future__ import annotations

import html
import re

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^\s*---+\s*$")
_ULI = re.compile(r"^(\s*)[-*]\s+(.*)$")
_OLI = re.compile(r"^(\s*)\d+\.\s+(.*)$")


def _slug(text: str) -> str:
    plain = re.sub(r"<[^>]+>", "", text)
    plain = re.sub(r"[^a-zA-Z0-9\s-]", "", plain).strip().lower()
    return re.sub(r"\s+", "-", plain)


def _inline(text: str) -> str:
    """Render inline spans. Code spans are protected from further formatting."""
    placeholders: list[str] = []

    def _stash_code(m: re.Match) -> str:
        placeholders.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(placeholders) - 1}\x00"

    text = _INLINE_CODE.sub(_stash_code, text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        text,
    )
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)

    def _restore(m: re.Match) -> str:
        return placeholders[int(m.group(1))]

    return re.sub(r"\x00(\d+)\x00", _restore, text)


def _render_table(block: list[str]) -> str:
    rows = [ln for ln in block if ln.strip()]
    if len(rows) < 2:
        return ""

    def _cells(line: str) -> list[str]:
        line = line.strip().strip("|")
        return [c.strip() for c in line.split("|")]

    header = _cells(rows[0])
    body = [_cells(r) for r in rows[2:]]
    out = ['<table class="doc-table"><thead><tr>']
    out += [f"<th>{_inline(h)}</th>" for h in header]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>")
        out += [f"<td>{_inline(c)}</td>" for c in r]
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _is_table_sep(line: str) -> bool:
    return bool(re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", line)) and "-" in line


def render_markdown(text: str) -> str:
    """Convert a Markdown string to an HTML fragment."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Fenced code block
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            buf: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code = html.escape("\n".join(buf))
            cls = f' class="lang-{html.escape(lang, quote=True)}"' if lang else ""
            out.append(f"<pre class=\"doc-pre\"><code{cls}>{code}</code></pre>")
            continue

        # Blank line
        if not line.strip():
            i += 1
            continue

        # Horizontal rule
        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue

        # Heading
        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            content = _inline(m.group(2).strip())
            anchor = _slug(m.group(2))
            out.append(f'<h{level} id="{anchor}">{content}</h{level}>')
            i += 1
            continue

        # Table (header line followed by a separator line)
        if "|" in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            block = [line, lines[i + 1]]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append(_render_table(block))
            continue

        # Blockquote
        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(_inline(lines[i].lstrip()[1:].lstrip()))
                i += 1
            out.append(f"<blockquote>{'<br>'.join(buf)}</blockquote>")
            continue

        # Lists (unordered / ordered), with simple one-level nesting by indent
        if _ULI.match(line) or _OLI.match(line):
            ordered = bool(_OLI.match(line))
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>")
            while i < n and (_ULI.match(lines[i]) or _OLI.match(lines[i])):
                mm = _OLI.match(lines[i]) if ordered else _ULI.match(lines[i])
                if not mm:
                    # switching list type: close and let outer loop restart
                    break
                out.append(f"<li>{_inline(mm.group(2).strip())}</li>")
                i += 1
            out.append(f"</{tag}>")
            continue

        # Paragraph (gather consecutive plain lines)
        buf = []
        while i < n and lines[i].strip() and not lines[i].strip().startswith("```") \
                and not _HEADING.match(lines[i]) and not _HR.match(lines[i]) \
                and not _ULI.match(lines[i]) and not _OLI.match(lines[i]) \
                and not lines[i].lstrip().startswith(">") \
                and not ("|" in lines[i] and i + 1 < n and _is_table_sep(lines[i + 1])):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(buf))}</p>")

    return "\n".join(out)


def extract_title(text: str) -> str:
    """First H1 in the document, or empty string."""
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 1:
            return re.sub(r"<[^>]+>", "", m.group(2)).strip()
    return ""
