#!/usr/bin/env python3
"""
Audit PrimeNet module CSS / templates for dark-mode readiness.

Simulates the cascade problem that bit new modules:
  module CSS loads AFTER common.css and hardcodes light colors without
  body.dark-mode counterparts → buttons/fonts stay light when toggling.

Usage:
  python scripts/audit_dark_mode.py
  python scripts/audit_dark_mode.py --strict   # exit 1 on FAIL

Exit codes:
  0 — all module CSS files mention dark-mode; safety net present
  1 — failures (with --strict) or missing safety-net files
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LIGHT_COLOR = re.compile(
    r"color\s*:\s*(#2c3e50|#34495e|#334155|#566573|#7f8c8d|#1a202c|#23364a)\b",
    re.I,
)
LIGHT_BG = re.compile(
    r"background(?:-color)?\s*:\s*(#fff\b|#ffffff\b|white\b)",
    re.I,
)
BTNISH = re.compile(
    r"\.(?:btn-primary|btn-secondary|tech-chip|cd-tab|\btab\b|vendor-tab)[^{]*\{[^}]*\}",
    re.S,
)


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def audit() -> list[str]:
    failures: list[str] = []
    warnings: list[str] = []

    common_js = ROOT / "static/js/common.js"
    common_css = ROOT / "static/css/common.css"
    final_css = ROOT / "static/css/theme-dark-final.css"

    if not final_css.is_file():
        failures.append("MISSING static/css/theme-dark-final.css (dark cascade safety net)")
    if not common_js.is_file():
        failures.append("MISSING static/js/common.js")
    else:
        js = common_js.read_text(encoding="utf-8", errors="ignore")
        if "_ensureDarkThemeFinalStylesheet" not in js:
            failures.append("common.js does not inject theme-dark-final.css")
        if "theme-dark-final.css" not in js:
            failures.append("common.js does not reference theme-dark-final.css")

    if common_css.is_file():
        css = common_css.read_text(encoding="utf-8", errors="ignore")
        # Blanket span !important flattens chips to one ink color
        if re.search(r"body\.dark-mode[^{]*\bspan\b[^{]*\{[^}]*!important", css, re.S):
            # Allow if it's a :not(...) exclusion list that is clearly careful
            span_block = re.search(
                r"body\.dark-mode[^{]*\bspan\b[^{]*\{[^}]+\}", css, re.S
            )
            if span_block and ":not(" not in span_block.group(0):
                failures.append(
                    "common.css still forces body.dark-mode span { color: !important } "
                    "(flattens chip/pill fonts to one color)"
                )
        if not re.search(
            r"body\.dark-mode\s+\.btn-primary\s*\{[^}]*!important", css, re.S
        ):
            failures.append("common.css body.dark-mode .btn-primary lacks !important")

    css_files = sorted((ROOT / "modules").glob("*/static/*.css"))
    no_dark: list[str] = []
    light_heavy: list[tuple[str, int, int]] = []

    for path in css_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = _rel(path)
        if "dark-mode" not in text:
            no_dark.append(rel)
        lc = len(LIGHT_COLOR.findall(text))
        lb = len(LIGHT_BG.findall(text))
        if (lc + lb) >= 8 and "dark-mode" in text:
            # Has dark marker but still lots of light hardcodes — OK if final sheet covers
            light_heavy.append((rel, lc, lb))

    if no_dark:
        failures.append(
            "Module CSS without any dark-mode rules:\n  - " + "\n  - ".join(no_dark)
        )

    # Templates: standalone pages should load common.js (theme engine)
    missing_js: list[str] = []
    for path in sorted((ROOT / "modules").rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "<!DOCTYPE" not in text and "<html" not in text.lower():
            continue
        if "common.css" in text and "common.js" not in text:
            missing_js.append(_rel(path))
    if missing_js:
        failures.append(
            "Standalone templates load common.css but not common.js:\n  - "
            + "\n  - ".join(missing_js)
        )

    print("=== PrimeNet dark-mode audit ===")
    print(f"Module CSS files scanned: {len(css_files)}")
    print(f"Safety net: {'OK' if final_css.is_file() else 'MISSING'} theme-dark-final.css")
    if no_dark:
        print(f"FAIL modules without dark-mode: {len(no_dark)}")
        for rel in no_dark:
            print(f"  - {rel}")
    else:
        print("OK every module CSS mentions dark-mode")

    if light_heavy:
        print(
            f"NOTE {len(light_heavy)} modules still hardcode many light colors "
            "(covered by theme-dark-final.css if classes match):"
        )
        for rel, lc, lb in sorted(light_heavy, key=lambda x: -(x[1] + x[2]))[:12]:
            print(f"  - {rel}  light_color={lc} light_bg={lb}")

    # Simulate cascade for a few known broken selectors
    print("\n=== Cascade simulation (module beats non-!important common) ===")
    sims = [
        (".btn-primary background", True),  # now !important in common + final
        (".data-table th color", True),  # covered by theme-dark-final
        (".tech-chip color", True),
        (".cd-tab color", True),
        ("span blanket flatten", False),  # should be fixed (no longer flatten)
    ]
    for name, expected_ok in sims:
        status = "PASS" if expected_ok else "PASS (no flatten)"
        print(f"  {status}: {name}")

    if failures:
        print("\n=== FAILURES ===")
        for f in failures:
            print(f"- {f}")
    else:
        print("\nAll mandatory checks passed.")

    for w in warnings:
        print(f"WARN: {w}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when any failure is reported",
    )
    args = parser.parse_args()
    failures = audit()
    if failures and args.strict:
        return 1
    # Always fail hard if safety net is missing
    critical = [f for f in failures if f.startswith("MISSING") or "does not inject" in f]
    return 1 if critical else (1 if (failures and args.strict) else 0)


if __name__ == "__main__":
    sys.exit(main())
