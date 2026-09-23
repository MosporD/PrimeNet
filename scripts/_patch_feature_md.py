# -*- coding: utf-8 -*-
import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "docs" / "feature.md"
text = p.read_text(encoding="utf-8")

old_intro = """Master map of every blueprint/portal under **NexusCore**. Dated session work still
lives in `progress.md`. Deep per-module memory lives in `docs/features/<slug>.md`.
Platform vision: `docs/NEXUSCORE_VISION.md`.

**Agents:** Before changing a feature, read this entry, then the linked brief, then
`python -m graphify query "<feature>"`. After code changes, append one dated line to the
brief **History** / **Plans**, and mirror material plan moves here if the NEXT pointer shifts."""

new_intro = """Master map of every blueprint/portal under **NexusCore**. Root `progress.md` is a
**brief daily journal** (topics only). Dated detail lives in
`docs/features/<slug>.progress.md`; implementation context in `docs/features/<slug>.md`.
Platform vision: `docs/NEXUSCORE_VISION.md`.

**Agents:** Before changing a feature, read this entry, the linked brief, and the
`.progress.md` file, then `python -m graphify query "<feature>"`. After code changes:
append to `<slug>.progress.md`, update brief **Plans** if needed, add one topic bullet
to root `progress.md`."""

if old_intro in text:
    text = text.replace(old_intro, new_intro)
else:
    print("WARN: intro not found")

parts = re.split(r"(?=^### )", text, flags=re.M)
out = []
for part in parts:
    if part.startswith("### ") and "| Slug |" in part:
        sm = re.search(r"\| Slug \| `([^`]+)` \|", part)
        if sm:
            slug = sm.group(1)
            part = re.sub(
                r"\*\*History:\*\*.*?(?=\n\*\*Plan:\*\*|\n### |\n## |\Z)",
                f"**Progress:** [`features/{slug}.progress.md`](features/{slug}.progress.md)\n\n",
                part,
                count=1,
                flags=re.S,
            )
    out.append(part)
text = "".join(out)

text = re.sub(
    r"\*\*History:\*\* 2026-09-16 — Phase 1 shipped.*?(?=\n\*\*Plan)",
    "**Progress:** [`features/nexpulse.progress.md`](features/nexpulse.progress.md)\n\n",
    text,
    count=1,
    flags=re.S,
)

text = text.replace(
    "_Catalog covering 51 PrimeNet/shared briefs + NexusCore portals. Keep in sync with `docs/features/<slug>.md`._",
    "_Catalog of briefs + progress files. Keep Plans aligned with `<slug>.progress.md` NEXT._",
)

# Add Progress column hint in blueprint tables if Brief line exists alone
def add_progress_row(m):
    slug = m.group(1)
    return (
        f"| Brief | [`features/{slug}.md`](features/{slug}.md) |\n"
        f"| Progress | [`features/{slug}.progress.md`](features/{slug}.progress.md) |"
    )

text2 = re.sub(
    r"\| Brief \| \[`features/([^`]+)\.md`\]\(features/\1\.md\) \|",
    add_progress_row,
    text,
)

p.write_text(text2, encoding="utf-8")
print("progress refs", text2.count("**Progress:**"))
print("Brief+Progress rows", text2.count("| Progress |"))
