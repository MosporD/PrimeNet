#!/usr/bin/env python3
"""
PrimeNet — Deep-dive deck for RADIO (RAN) ENGINEERS.

Not a developer deck: the depth is radio-engineering depth — KPI recipes,
detection algorithms with real thresholds, CM/RET workflows, data cadence.
Built as a demo companion: constellation dark theme mirrors the app, and
amber "SWITCH TO TOOL" checkpoints carry exact click-paths.
"""

import math
import random
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---------------------------------------------------------------- palette ----
BG        = RGBColor(0x0F, 0x17, 0x22)
BG2       = RGBColor(0x0B, 0x11, 0x1A)
PANEL     = RGBColor(0x18, 0x22, 0x30)
PANEL2    = RGBColor(0x1B, 0x27, 0x36)
BORDER    = RGBColor(0x30, 0x42, 0x58)
TEXT      = RGBColor(0xE8, 0xEE, 0xF7)
MUTED     = RGBColor(0xA9, 0xB7, 0xC9)
FAINT     = RGBColor(0x74, 0x86, 0x9C)
ACCENT    = RGBColor(0x8B, 0xC1, 0xFF)
TEAL      = RGBColor(0x3D, 0xD6, 0xB0)
GOLD      = RGBColor(0xF2, 0xB8, 0x4B)
PURPLE    = RGBColor(0xB0, 0x8C, 0xFF)
CRIT      = RGBColor(0xE5, 0x54, 0x8A)
ORANGE    = RGBColor(0xE9, 0x91, 0x3A)
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
CODEBG    = RGBColor(0x0C, 0x13, 0x1D)

EMU_IN = 914400
SW, SH = 13.333, 7.5

prs = Presentation()
prs.slide_width  = Emu(int(SW * EMU_IN))
prs.slide_height = Emu(int(SH * EMU_IN))
BLANK = prs.slide_layouts[6]

FONT   = "Segoe UI"
FONT_L = "Segoe UI Light"
MONO   = "Consolas"

_slide_no = 0


# --------------------------------------------------------------- helpers -----
def _set_fill(shape, color):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()


def _no_shadow(shape):
    sp = shape._element
    spPr = sp.find(qn('p:spPr'))
    if spPr is None:
        return
    for tag in ('a:effectLst', 'a:effectDag'):
        for el in spPr.findall(qn(tag)):
            spPr.remove(el)
    spPr.append(spPr.makeelement(qn('a:effectLst'), {}))


def rect(slide, x, y, w, h, fill=None, line=None, line_w=1.0, radius=0.06,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    sp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w)
    _no_shadow(sp)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sp.adjustments[0] = radius
        except Exception:
            pass
    return sp


def line(slide, x1, y1, x2, y2, color=BORDER, w=1.0):
    ln = slide.shapes.add_connector(2, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    ln.line.color.rgb = color
    ln.line.width = Pt(w)
    _no_shadow(ln)
    return ln


def text(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         space_after=4, line_spacing=1.06, wrap=True):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.auto_size = MSO_AUTO_SIZE.NONE
    for m in ('left', 'right', 'top', 'bottom'):
        setattr(tf, f'margin_{m}', 0)
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        p.space_before = Pt(0)
        p.line_spacing = line_spacing
        for (txt, size, color, bold, *rest) in para:
            fname = rest[0] if len(rest) > 0 and rest[0] else FONT
            italic = rest[1] if len(rest) > 1 else False
            r = p.add_run()
            r.text = txt
            r.font.size = Pt(size)
            r.font.color.rgb = color
            r.font.bold = bold
            r.font.name = fname
            r.font.italic = italic
    return tb


def slide_base(divider=False):
    s = prs.slides.add_slide(BLANK)
    rect(s, -0.1, -0.1, SW + 0.2, SH + 0.2, fill=(BG2 if divider else BG),
         shape=MSO_SHAPE.RECTANGLE)
    return s


def constellation(slide, n=46, seed=1, box=(0, 0, SW, SH), link=1.7):
    random.seed(seed)
    x0, y0, x1, y1 = box
    pts = [(random.uniform(x0, x1), random.uniform(y0, y1)) for _ in range(n)]
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            if d < link and random.random() < 0.5:
                line(slide, a[0], a[1], b[0], b[1], color=RGBColor(0x22, 0x30, 0x44), w=0.75)
    for (px, py) in pts:
        r = random.choice([0.02, 0.03, 0.045, 0.03])
        c = random.choice([ACCENT, TEAL, RGBColor(0x3A, 0x4A, 0x60), MUTED, ACCENT])
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(px), Inches(py), Inches(r), Inches(r))
        _set_fill(dot, c)
        _no_shadow(dot)


def footer(slide, section=""):
    global _slide_no
    _slide_no += 1
    line(slide, 0.55, SH - 0.52, SW - 0.55, SH - 0.52, color=RGBColor(0x22, 0x30, 0x42), w=0.75)
    text(slide, 0.55, SH - 0.47, 6.5, 0.3,
         [[("PrimeNet", 9, ACCENT, True), ("  ·  RAN Engineering Deep-Dive", 9, FAINT, False)]],
         anchor=MSO_ANCHOR.MIDDLE)
    if section:
        text(slide, SW / 2 - 2.5, SH - 0.47, 5.0, 0.3, [[(section, 9, FAINT, False)]],
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(slide, SW - 2.05, SH - 0.47, 1.5, 0.3, [[(f"{_slide_no:02d}", 9, MUTED, True)]],
         align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)


def header(slide, kicker, title, kicker_color=ACCENT):
    rect(slide, 0.55, 0.5, 0.09, 0.62, fill=kicker_color, shape=MSO_SHAPE.RECTANGLE)
    text(slide, 0.78, 0.46, 11.8, 0.3, [[(kicker.upper(), 11, kicker_color, True)]])
    text(slide, 0.77, 0.7, 12.0, 0.6, [[(title, 25, TEXT, True, FONT_L)]])


def chip(slide, x, y, w, label, color, h=0.34, size=10.5):
    rect(slide, x, y, w, h, fill=None, line=color, line_w=1.25, radius=0.5)
    text(slide, x, y - 0.005, w, h, [[(label, size, color, True)]],
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def bullets(slide, x, y, w, h, items, size=13, gap=7, lead=ACCENT, tcolor=TEXT,
            line_spacing=1.05):
    paras = []
    for it in items:
        if isinstance(it, tuple):
            lead_t, rest = it
            paras.append([("▸  ", size, lead, True),
                          (lead_t, size, WHITE, True),
                          (rest, size, tcolor, False)])
        else:
            paras.append([("▸  ", size, lead, True), (it, size, tcolor, False)])
    text(slide, x, y, w, h, paras, space_after=gap, line_spacing=line_spacing)


def demo_cue(slide, y, title, steps, watch=None):
    x, w = 0.55, SW - 1.10
    h = 1.3 if watch else 1.06
    rect(slide, x, y, w, h, fill=RGBColor(0x22, 0x1C, 0x0E), line=GOLD, line_w=1.25, radius=0.05)
    rect(slide, x, y, 0.09, h, fill=GOLD, shape=MSO_SHAPE.RECTANGLE)
    text(slide, x + 0.28, y + 0.12, 6.5, 0.3,
         [[("⟳  SWITCH TO TOOL", 12, GOLD, True),
           ("   — live demo checkpoint", 10.5, RGBColor(0xC9, 0xB0, 0x82), False, FONT, True)]])
    text(slide, x + 0.28, y + 0.44, w - 0.6, 0.3, [[(title, 12, TEXT, True)]])
    text(slide, x + 0.28, y + 0.71, w - 0.6, 0.4,
         [[("Click path:  ", 10.5, GOLD, True), (steps, 10.5, MUTED, False, MONO)]])
    if watch:
        text(slide, x + 0.28, y + 0.98, w - 0.6, 0.3,
             [[("Point out:  ", 10.5, TEAL, True), (watch, 10.5, MUTED, False)]])
    return h


def formula_card(slide, x, y, w, h, title, lines_, title_color=TEAL):
    rect(slide, x, y, w, h, fill=CODEBG, line=BORDER, radius=0.04)
    text(slide, x + 0.25, y + 0.13, w - 0.45, 0.3, [[(title, 11, title_color, True)]])
    yy = y + 0.48
    for t, c in lines_:
        text(slide, x + 0.27, yy, w - 0.5, 0.3, [[(t, 11, c, False, MONO)]])
        yy += 0.3
    return yy


# ============================================================ 1 · TITLE
s = slide_base(divider=True)
constellation(s, n=70, seed=7, link=1.9)
text(s, 0.9, 1.45, 11.5, 0.4, [[("FOR RADIO ENGINEERS — HOW IT ACTUALLY WORKS", 15, ACCENT, True)]])
text(s, 0.85, 1.9, 11.6, 1.5, [[("PrimeNet", 62, WHITE, True, FONT_L)]])
text(s, 0.9, 3.1, 11.5, 0.6,
     [[("KPIs, detections, CM & RET — the radio engineering inside the tool", 18, MUTED, False, FONT_L)]])
chips = [("Nokia + Huawei", TEAL), ("2G · 3G · 4G · 5G", PURPLE),
         ("Hourly & daily PM", ACCENT), ("CM read + governed write", GOLD)]
cx = 0.9
for lab, col in chips:
    wch = 0.24 + 0.105 * len(lab)
    chip(s, cx, 4.0, wch, lab, col, h=0.42, size=11.5)
    cx += wch + 0.22
rect(s, 0.9, 5.0, 11.5, 1.05, fill=RGBColor(0x14, 0x1E, 0x2B), line=GOLD, line_w=1.0, radius=0.05)
rect(s, 0.9, 5.0, 0.09, 1.05, fill=GOLD, shape=MSO_SHAPE.RECTANGLE)
text(s, 1.15, 5.15, 11.0, 0.8,
     [[("⟳  This is a companion deck.  ", 12.5, GOLD, True),
       ("Amber bands mark ", 12, MUTED, False),
       ("live-tool checkpoints", 12, TEXT, True),
       (" — keep PrimeNet open in a second window and switch whenever you see one.", 12, MUTED, False)],
      [("Slides explain the logic behind each screen; the tool shows it running on your network.", 11, FAINT, False, FONT, True)]],
     space_after=5)
text(s, 0.9, 6.5, 11.5, 0.3, [[("Presenter: Malek Mohammad   ·   Audience: RF / RAN optimization engineers", 11, FAINT, False)]])

# ============================================================ 2 · HOW TO RUN
s = slide_base()
header(s, "Presenter guide", "How to run this session")
text(s, 0.55, 1.35, 7.2, 0.4, [[("The two-window rhythm", 14, TEAL, True)]])
bullets(s, 0.55, 1.75, 7.2, 3.0, [
    ("Deck = the logic. ", "Thresholds, formulas, and workflows the UI doesn't spell out — why a cell got flagged."),
    ("Tool = your network. ", "Every detection shown on a slide is then shown live, on real cells."),
    ("Layout: ", "deck on one half of the screen, PrimeNet on the other — or two monitors."),
    ("Cadence: ", "explain one detection → amber checkpoint → find a real example live → back to deck."),
    ("Login before starting ", "and keep a busy area in mind — live examples land better than slides."),
], size=13, gap=9)
rx, rw = 8.15, 4.65
rect(s, rx, 1.35, rw, 4.55, fill=PANEL, line=BORDER, radius=0.04)
text(s, rx + 0.3, 1.55, rw - 0.6, 0.3, [[("SLIDE LEGEND", 11, MUTED, True)]])
legend = [
    (GOLD,  "⟳ SWITCH TO TOOL", "Stop talking, start clicking. Click-path is monospaced."),
    (TEAL,  "Point out",        "What the audience must notice on the live screen."),
    (ACCENT, "▸ blue bullets",  "The radio logic — thresholds, weights, evidence."),
    (CRIT,  "formula cards",    "The actual scoring math the tool runs, verbatim."),
]
yy = 2.0
for col, lab, desc in legend:
    rect(s, rx + 0.3, yy + 0.05, 0.16, 0.16, fill=col, shape=MSO_SHAPE.OVAL)
    text(s, rx + 0.6, yy - 0.05, rw - 0.9, 0.3, [[(lab, 12, col, True)]])
    text(s, rx + 0.6, yy + 0.26, rw - 0.9, 0.5, [[(desc, 10.5, MUTED, False)]])
    yy += 0.86
text(s, rx + 0.3, yy + 0.05, rw - 0.6, 0.6,
     [[("No live network? The deck stands alone — every checkpoint has enough context to narrate.", 10.5, FAINT, False, FONT, True)]])
footer(s, "Presenter guide")

# ============================================================ 3 · AGENDA
s = slide_base()
header(s, "Roadmap", "What we'll cover")
agenda = [
    ("01", "Your day in PrimeNet", "The monitor → detect → diagnose → change → verify loop", ACCENT),
    ("02", "The data underneath", "PM cadence, sources, metadata — what \"latest\" means", TEAL),
    ("03", "KPIs across two vendors", "Recipes & aliases: one KPI name, per-vendor counters", PURPLE),
    ("04", "How issues are scored", "Severity, evidence, and reading an issue card", GOLD),
    ("05", "The detections, in depth", "Sleeping cells · overshooting · neighbors · capacity", CRIT),
    ("06", "CM: reading the network", "MO trees, live vs plan config, parameter dictionary", ACCENT),
    ("07", "Audits, changes & RET", "Golden-parameter audit, change impact, safe tilt writes", TEAL),
    ("08", "The daily loop & trust", "Morning report, sector health, data freshness", PURPLE),
]
colw, rowh = 5.9, 1.18
x0, y0 = 0.6, 1.45
for i, (n, t, d, col) in enumerate(agenda):
    cx = x0 + (i % 2) * (colw + 0.35)
    cy = y0 + (i // 2) * (rowh + 0.12)
    rect(s, cx, cy, colw, rowh, fill=PANEL, line=BORDER, radius=0.06)
    rect(s, cx, cy, 0.07, rowh, fill=col, shape=MSO_SHAPE.RECTANGLE)
    text(s, cx + 0.28, cy + 0.12, 1.2, 0.9, [[(n, 30, col, True, FONT_L)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, cx + 1.35, cy + 0.19, colw - 1.5, 0.4, [[(t, 14.5, TEXT, True)]])
    text(s, cx + 1.35, cy + 0.62, colw - 1.5, 0.4, [[(d, 11, MUTED, False)]])
footer(s, "Roadmap")

# ============================================================ 4 · WORKFLOW LOOP
s = slide_base()
header(s, "Section 01", "Your day in PrimeNet: one optimization loop")
stages = [
    ("MONITOR", "Morning Report\nSector Health\nNetwork Map / Heatmap", ACCENT),
    ("DETECT", "Sleeping Cells\nOvershooting\nCapacity Hotspots\nNeighbor Quality", CRIT),
    ("DIAGNOSE", "Performance Explorer\nKPI trends & evidence\nParameter Dictionary", TEAL),
    ("CHANGE", "RET tilt / CM edits\nExcel mass-modify\n(plan first, then apply)", GOLD),
    ("VERIFY", "Change Impact Tracker\nConfig History\nnext-day KPIs", PURPLE),
]
bw = 2.28
for i, (t, d, col) in enumerate(stages):
    cx = 0.55 + i * (bw + 0.18)
    rect(s, cx, 1.5, bw, 1.85, fill=PANEL, line=col, line_w=1.25, radius=0.06)
    rect(s, cx, 1.5, bw, 0.42, fill=col, shape=MSO_SHAPE.RECTANGLE)
    text(s, cx, 1.5, bw, 0.42, [[(t, 12, BG, True)]], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, cx + 0.15, 2.02, bw - 0.3, 1.25, [[(d, 10.5, MUTED, False)]], line_spacing=1.15)
    if i < 4:
        text(s, cx + bw - 0.02, 2.2, 0.22, 0.4, [[("→", 18, FAINT, True)]])
# loop-back arrow note
text(s, 0.55, 3.5, 12.2, 0.3,
     [[("↺  Verify feeds Monitor — every applied change shows up in tomorrow's morning report and impact tracker.", 11.5, FAINT, False, FONT, True)]])
bullets(s, 0.55, 3.95, 12.1, 1.6, [
    ("Everything is cell-level and evidence-backed. ", "Each detection carries the KPI values that triggered it — no black-box 'AI says so'."),
    ("Both vendors, one workflow. ", "Nokia and Huawei cells appear in the same lists with the same severities; you don't switch tools per vendor."),
    ("Reads are free, writes are staged. ", "All analytics are read-only; tilt/parameter changes go through an explicit plan → apply → history flow."),
], size=12.5, gap=8)
footer(s, "01 · Workflow")
demo_cue(s, 5.72,
         "Show the dashboard: the module deck maps 1:1 to this loop.",
         "Login → Dashboard  (hover the Radio Optimization section)")

# ============================================================ 5 · DATA UNDERNEATH
s = slide_base()
header(s, "Section 02", "The data underneath")
# left: sources & cadence
text(s, 0.55, 1.32, 6.1, 0.4, [[("Where the numbers come from", 14, TEAL, True)]])
srcs = [
    ("Nokia PM", "NetAct exports over SFTP", "hourly + daily", ACCENT),
    ("Huawei PM", "U2020 exports over SFTP", "hourly + daily", CRIT),
    ("Metadata", "site/cell inventory, azimuths, coords, on-air state", "snapshot", TEAL),
]
yy = 1.72
for name, d, cad, col in srcs:
    rect(s, 0.55, yy, 6.1, 0.72, fill=PANEL, line=BORDER, radius=0.06)
    rect(s, 0.55, yy, 0.07, 0.72, fill=col, shape=MSO_SHAPE.RECTANGLE)
    text(s, 0.8, yy + 0.09, 1.6, 0.3, [[(name, 12, TEXT, True)]])
    text(s, 0.8, yy + 0.38, 4.3, 0.3, [[(d, 10, MUTED, False)]])
    text(s, 5.0, yy + 0.09, 1.55, 0.5, [[(cad, 10.5, col, True)]], align=PP_ALIGN.RIGHT)
    yy += 0.82
bullets(s, 0.55, 4.35, 6.1, 1.9, [
    ("Hourly ", "drives near-real-time views (sector health, busy-hour checks)."),
    ("Daily ", "drives baselines and detections — a stable day-level series per cell."),
    ("Metadata joins everything: ", "cell → site, area, vendor, technology, azimuth, on-air state."),
], size=12, gap=7)
# right: per-RAT organization
rx, rw = 6.95, 5.8
rect(s, rx, 1.32, rw, 4.0, fill=CODEBG, line=BORDER, radius=0.04)
text(s, rx + 0.28, 1.5, rw - 0.5, 0.3, [[("HOW PM IS ORGANIZED", 11, MUTED, True)]])
org = [
    ("per vendor    nokia · huawei", ACCENT),
    ("per RAT       2G · 3G · 4G · 5G", TEAL),
    ("              (4G FDD/TDD share the 4G table)", FAINT),
    ("per cadence   hourly · daily", PURPLE),
    ("per scope     cells · groups (clusters/areas)", GOLD),
    ("", MUTED),
    ("KPI columns are detected automatically at", MUTED),
    ("import — new counters in a vendor export", MUTED),
    ("appear as new KPIs, no mapping to maintain.", MUTED),
]
yy = 1.92
for t, c in org:
    text(s, rx + 0.3, yy, rw - 0.55, 0.3, [[(t, 11.5, c, False, MONO)]])
    yy += 0.345
text(s, 0.55, 5.5, 12.2, 0.5,
     [[("Why you should care:  ", 12, TEAL, True),
       ("every detection later in this deck runs on the daily per-cell series; if a day's file is late, that day is simply absent — the tool never interpolates fake data.", 12, MUTED, False)]])
footer(s, "02 · Data")

# ============================================================ 6 · KPI RECIPES
s = slide_base()
header(s, "Section 03", "One KPI, two vendors: recipes & aliases")
text(s, 0.55, 1.28, 12.2, 0.35,
     [[("You ask for a concept (\"utilization\"); PrimeNet resolves the right per-vendor counter column automatically:", 12, MUTED, False)]])
# recipe table
rows = [
    ("utilization", "higher = worse", "DL/UL PRB Usage Rate(%)", "E-UTRAN Avg PRB usage per TTI DL", CRIT),
    ("users", "higher = worse", "Average User Number · RRC Connected Users", "Active Users", ORANGE),
    ("traffic", "higher = worse", "Traffic Volume · Payload", "Data Volume · DL/UL Traffic", GOLD),
    ("throughput", "lower = worse", "User/Cell Throughput", "Average Throughput", TEAL),
    ("accessibility / retainability / mobility / interference", "category presets", "vendor formulas per RAT", "vendor formulas per RAT", PURPLE),
]
ty = 1.75
rect(s, 0.55, ty, 12.2, 0.42, fill=PANEL2, line=None, radius=0.03)
for cx, lab, wd in ((0.75, "RECIPE", 3.2), (4.05, "DIRECTION", 1.7), (5.9, "HUAWEI COUNTERS (examples)", 3.4), (9.45, "NOKIA COUNTERS (examples)", 3.2)):
    text(s, cx, ty + 0.06, wd, 0.3, [[(lab, 10, MUTED, True)]])
yy = ty + 0.5
for rec, direc, hw, nk, col in rows:
    rect(s, 0.55, yy, 12.2, 0.58, fill=PANEL, line=BORDER, radius=0.03)
    rect(s, 0.55, yy, 0.06, 0.58, fill=col, shape=MSO_SHAPE.RECTANGLE)
    text(s, 0.75, yy + 0.05, 3.25, 0.5, [[(rec, 11, TEXT, True, MONO)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 4.05, yy + 0.05, 1.75, 0.5, [[(direc, 10, col, True)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 5.9, yy + 0.05, 3.4, 0.5, [[(hw, 9.5, MUTED, False)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 9.45, yy + 0.05, 3.25, 0.5, [[(nk, 9.5, MUTED, False)]], anchor=MSO_ANCHOR.MIDDLE)
    yy += 0.64
text(s, 0.55, yy + 0.05, 12.2, 0.5,
     [[("Matching is normalized (case/punctuation-insensitive) per vendor + RAT — so cross-vendor comparisons like \"top PRB utilization cells network-wide\" are one query, not two exports and a VLOOKUP.", 11.5, MUTED, False)]])
footer(s, "03 · KPIs")
demo_cue(s, 5.82,
         "Query the same KPI across Nokia and Huawei cells in one screen.",
         "Dashboard → Performance Explorer → vendor: All → pick a KPI → Top-N")

# ============================================================ 7 · SCORING MODEL
s = slide_base()
header(s, "Section 04", "How issues are scored (read this once, use it everywhere)")
bullets(s, 0.55, 1.38, 6.15, 2.6, [
    ("Additive, capped signals. ", "Each detection sums a few capped penalty terms; the total is clipped to 0–100."),
    ("Severity is just a banding of the score ", "— same thresholds in every module (right)."),
    ("Evidence rides along. ", "Every issue carries the raw KPI values (pre / post / delta, dates, distances) that produced its score."),
    ("Stable identity. ", "The same cell + problem keeps the same issue ID across days — you can track it until it's fixed."),
], size=12.5, gap=8)
# severity bands
rect(s, 0.55, 4.15, 6.15, 1.5, fill=CODEBG, line=BORDER, radius=0.04)
text(s, 0.83, 4.28, 5.6, 0.3, [[("SEVERITY BANDS (ALL MODULES)", 11, MUTED, True)]])
bands = [("Critical", "≥ 85", CRIT), ("High", "≥ 70", ORANGE), ("Medium", "≥ 45", GOLD), ("Low", "> 0", TEAL), ("Info", "0", FAINT)]
cx = 0.85
for lab, thr, col in bands:
    rect(s, cx, 4.68, 1.06, 0.62, fill=PANEL, line=col, line_w=1.25, radius=0.1)
    text(s, cx, 4.74, 1.06, 0.3, [[(lab, 10.5, col, True)]], align=PP_ALIGN.CENTER)
    text(s, cx, 5.0, 1.06, 0.3, [[(thr, 10.5, TEXT, False, MONO)]], align=PP_ALIGN.CENTER)
    cx += 1.14
# anatomy of an issue card
rx, rw = 7.0, 5.75
rect(s, rx, 1.38, rw, 4.27, fill=PANEL, line=BORDER, radius=0.04)
text(s, rx + 0.28, 1.52, rw - 0.5, 0.3, [[("ANATOMY OF AN ISSUE CARD", 11, MUTED, True)]])
card = [
    ("Sleeping cell AMM0416_L18_1", 13, CRIT, True, FONT),
    ("Critical · score 92 · Availability · Huawei · 4G", 10, MUTED, False, FONT),
    ("", 4, MUTED, False, FONT),
    ("\"CM state Active but 'Traffic Volume' flatlined for 3 day(s):", 10.5, TEXT, False, MONO),
    ("  latest=0.01 vs baseline avg 412.6 over previous 7 day(s)\"", 10.5, TEXT, False, MONO),
    ("", 4, MUTED, False, FONT),
    ("evidence: { kpi, days_asleep, baseline_avg,", 10.5, GOLD, False, MONO),
    ("            quiet_cutoff, recent[], baseline[] }", 10.5, GOLD, False, MONO),
    ("", 4, MUTED, False, FONT),
    ("recommendation: check alarms, TX path, RET/RRU,", 10.5, TEAL, False, MONO),
    ("  transmission — likely silent outage or barred cell", 10.5, TEAL, False, MONO),
]
yy = 1.92
for t, sz, c, b, f in card:
    text(s, rx + 0.3, yy, rw - 0.55, 0.32, [[(t, sz, c, b, f)]])
    yy += 0.31 if t else 0.12
text(s, rx + 0.28, yy + 0.12, rw - 0.5, 0.4,
     [[("Title → what · Summary → why · Evidence → proof · Recommendation → next action", 10, FAINT, False, FONT, True)]])
footer(s, "04 · Scoring")

# ============================================================ 8 · SLEEPING CELLS
s = slide_base()
header(s, "Section 05", "Detection 1 — Sleeping cells", kicker_color=CRIT)
text(s, 0.55, 1.28, 12.2, 0.35,
     [[("Definition:  ", 12, CRIT, True),
       ("a cell that is on-air per CM (activity = Active) but whose daily traffic collapsed to ~zero against its own baseline — a silent outage no alarm caught.", 12, MUTED, False)]])
bullets(s, 0.55, 1.8, 6.15, 3.3, [
    ("Baseline = the cell's own history. ", "7 previous days of daily traffic (or users, if no traffic KPI exists for that table)."),
    ("Recent window = last 2 days. ", "The cell is a candidate only if its best recent day is still below the quiet cutoff."),
    ("Quiet cutoff is relative: ", "2% of the baseline average, floored at 0.05 — a small cell isn't flagged for being small."),
    ("Low-traffic cells excluded: ", "baseline average < 1.0 (KPI units) is ignored — nothing meaningful to lose."),
    ("Days-asleep counts back ", "consecutive quiet days from the newest sample — it can exceed the 2-day window."),
], size=12, gap=8)
formula_card(s, 7.0, 1.8, 5.75, 2.35, "SCORE (0–100)", [
    ("score = 45                    # base: it IS asleep", TEAL),
    ("      + min(25, √baseline_avg)  # bigger cell,", TEXT),
    ("                                # bigger loss", FAINT),
    ("      + min(30, days_asleep×10) # longer = worse", TEXT),
    ("", MUTED),
    ("quiet_cutoff = max(0.05, 0.02 × baseline_avg)", GOLD),
])
text(s, 7.0, 4.35, 5.75, 0.75,
     [[("Reading it:  ", 11, TEAL, True),
       ("a busy cell (baseline 400+) asleep 3 days lands ≈ 45+20+30 = 95 → Critical. A quiet rural cell asleep 1 day ≈ 45+3+10 = 58 → Medium.", 11, MUTED, False)]])
footer(s, "05 · Detections")
demo_cue(s, 5.55,
         "Open Sleeping Cells; expand one issue and show recent[] vs baseline[] in the evidence.",
         "Dashboard → Radio Optimization → Sleeping Cell Detector",
         watch="CM says Active, PM says dead — that gap is the whole detection.")

# ============================================================ 9 · OVERSHOOTING
s = slide_base()
header(s, "Section 05", "Detection 2 — Overshooting", kicker_color=ORANGE)
text(s, 0.55, 1.28, 12.2, 0.35,
     [[("Definition:  ", 12, ORANGE, True),
       ("a cell handing over to neighbors far beyond its intended footprint — serving where it shouldn't, degrading HO performance and polluting the far cell's area.", 12, MUTED, False)]])
bullets(s, 0.55, 1.8, 6.15, 3.2, [
    ("Source: the HO relation matrix. ", "Per source→target neighbor line: attempts, failures, success rate, inter-site distance (min 5 attempts to count)."),
    ("Distance gate: ", "relations under 8 km are ignored — normal grid geometry, not overshooting."),
    ("Three penalty terms: ", "distance beyond 8 km, HO failure ratio, and HO success rate below 95%."),
    ("Keep threshold: ", "score < 30 is dropped — only actionable candidates surface."),
    ("First-pass heuristic by design: ", "needs no TA/MR/RSRP data; confirm with TA or drive-test evidence before tilting."),
], size=12, gap=8)
formula_card(s, 7.0, 1.8, 5.75, 2.3, "SCORE (0–100)", [
    ("if distance < 8 km: skip", FAINT),
    ("score = min(45, (distance − 8) × 4)", TEXT),
    ("      + min(25, failures/attempts × 100)", TEXT),
    ("      + max(0, 95 − HO_success_rate)", TEXT),
    ("keep if score ≥ 30", GOLD),
])
text(s, 7.0, 4.3, 5.75, 0.8,
     [[("Action path:  ", 11, TEAL, True),
       ("evidence includes source azimuth → check the bearing, then downtilt (RET module), power, or clean the neighbor plan. 15 km + failing HOs ≈ 28+x → strong candidate.", 11, MUTED, False)]])
footer(s, "05 · Detections")
demo_cue(s, 5.55,
         "Sort by score; pick a candidate and cross-check its azimuth & distance on the map.",
         "Radio Optimization → Overshooting Detector  →  Network Map (same cell)",
         watch="Far-target distance + failure ratio in the evidence block — then the geometry on the map.")

# ============================================================ 10 · NEIGHBOR QUALITY
s = slide_base()
header(s, "Section 05", "Detection 3 — Neighbor quality", kicker_color=TEAL)
text(s, 0.55, 1.28, 12.2, 0.35,
     [[("Every defined neighbor relation is scored by summing independent penalties — one bad relation can fail for several reasons at once:", 12, MUTED, False)]])
# penalty table
pens = [
    ("Poor HO success", "(95 − SR) × 1.4", "SR 88% → 9.8 pts; missing SR data → flat 10", CRIT),
    ("HO failures", "min(35, fail/attempts × 100)", "failure ratio capped at 35 pts", ORANGE),
    ("Excessive distance", "+20 if ≥ 12 km", "geometry sanity check on the relation", GOLD),
    ("Missing reciprocal", "+15 if B→A not defined", "one-way neighbors break return mobility", PURPLE),
    ("Cross-vendor edge", "+8 if vendors differ", "Nokia↔Huawei borders need extra attention", ACCENT),
]
ty = 1.78
rect(s, 0.55, ty, 12.2, 0.4, fill=PANEL2, line=None, radius=0.03)
for cx, lab, wd in ((0.75, "SIGNAL", 2.6), (3.45, "PENALTY", 3.1), (6.7, "READING IT", 5.9)):
    text(s, cx, ty + 0.05, wd, 0.3, [[(lab, 10, MUTED, True)]])
yy = ty + 0.48
for sig, pen, note, col in pens:
    rect(s, 0.55, yy, 12.2, 0.56, fill=PANEL, line=BORDER, radius=0.03)
    rect(s, 0.55, yy, 0.06, 0.56, fill=col, shape=MSO_SHAPE.RECTANGLE)
    text(s, 0.75, yy + 0.04, 2.65, 0.5, [[(sig, 11, TEXT, True)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 3.45, yy + 0.04, 3.15, 0.5, [[(pen, 10.5, col, True, MONO)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 6.7, yy + 0.04, 5.9, 0.5, [[(note, 10, MUTED, False)]], anchor=MSO_ANCHOR.MIDDLE)
    yy += 0.62
text(s, 0.55, yy + 0.03, 12.2, 0.35,
     [[("Relations need ≥10 HO attempts to be judged; total score < 25 is discarded. Summary strings are engineer-readable: ", 11, MUTED, False),
       ("\"HO SR 88.2%, 214 failed HOs, missing reciprocal, 14.1 km\"", 11, TEAL, False, MONO)]])
footer(s, "05 · Detections")
demo_cue(s, 5.85,
         "Filter to one area; show a relation failing on multiple penalties at once.",
         "Radio Optimization → Neighbor Quality Analyzer → area filter")

# ============================================================ 11 · CAPACITY + COVERAGE
s = slide_base()
header(s, "Section 05", "Detections 4 & 5 — Capacity hotspots · Layer gaps", kicker_color=GOLD)
# left: capacity
rect(s, 0.55, 1.4, 6.05, 4.1, fill=PANEL, line=GOLD, line_w=1.25, radius=0.05)
text(s, 0.82, 1.55, 5.6, 0.3, [[("CAPACITY HOTSPOTS", 12.5, GOLD, True)]])
text(s, 0.82, 1.9, 5.55, 0.7,
     [[("Finds cells whose PRB utilization is both rising and already high — growth pressure, not a one-day spike.", 11, MUTED, False)]])
formula_card(s, 0.82, 2.6, 5.5, 1.7, "SCORE", [
    ("delta = |latest − baseline| utilization", TEXT),
    ("score = min(45, delta × 2)", TEXT),
    ("      + max(0, latest − 70) × 1.2", TEXT),
    ("keep if score ≥ 20", GOLD),
])
text(s, 0.82, 4.42, 5.5, 0.95,
     [[("The 70% knee:  ", 10.5, TEAL, True),
       ("below ~70% PRB, users rarely feel it; each point above 70 adds 1.2 pts. Recommendation: busy-hour PRB/users review → carrier add or sector split.", 10.5, MUTED, False)]])
# right: layer gaps
rect(s, 6.75, 1.4, 6.0, 4.1, fill=PANEL, line=PURPLE, line_w=1.25, radius=0.05)
text(s, 7.02, 1.55, 5.5, 0.3, [[("LAYER COVERAGE GAPS", 12.5, PURPLE, True)]])
text(s, 7.02, 1.9, 5.5, 0.7,
     [[("Inventory-based (no PM needed): per sector, which technology layers exist vs which the grid design expects.", 11, MUTED, False)]])
formula_card(s, 7.02, 2.6, 5.45, 1.7, "SCORE", [
    ("+35 if LTE missing entirely", TEXT),
    ("+20 if 3G missing", TEXT),
    ("+min(35, missing_layers × 7)", TEXT),
    ("  (per absent LTE band, e.g. L18/L21)", FAINT),
])
text(s, 7.02, 4.42, 5.45, 0.95,
     [[("Use it for:  ", 10.5, TEAL, True),
       ("finding sectors where a band was never integrated, decommissioned by mistake, or metadata is stale — validate design before chasing 'coverage complaints'.", 10.5, MUTED, False)]])
footer(s, "05 · Detections")
demo_cue(s, 5.72,
         "Show a hotspot cell's utilization trend, then a sector with a missing band.",
         "Capacity Hotspots → evidence  ·  then  Layer Coverage Gaps")

# ============================================================ 12 · CM READING
s = slide_base()
header(s, "Section 06", "CM: reading the live network")
bullets(s, 0.55, 1.38, 6.1, 3.5, [
    ("Live config on demand. ", "PrimeNet reads current parameter values straight from the OSS — NetAct for Nokia, U2020 for Huawei — not from a stale weekly export."),
    ("The MO tree is your address system. ", "Nokia: PLMN → RNC/BSC → WBTS/WCEL (3G), MRBTS → LNCEL (4G). Every cell/parameter has one distinguished name (DN)."),
    ("Live vs plan. ", "Reads target the actual network; writes go to a plan configuration first — nothing edits live directly."),
    ("Huawei side speaks MML. ", "The same UI drives LST/MOD commands under the hood; responses are parsed into the same tables."),
    ("Parameter Dictionary: ", "~19,000 Huawei parameter reference pages searchable offline — meaning, range, impact, before you touch anything."),
], size=12, gap=8)
# right: DN example card
rx, rw = 6.9, 5.85
rect(s, rx, 1.38, rw, 3.5, fill=CODEBG, line=BORDER, radius=0.04)
text(s, rx + 0.28, 1.52, rw - 0.5, 0.3, [[("ONE CELL, TWO VENDORS", 11, MUTED, True)]])
dn = [
    ("Nokia (3G cell):", TEAL),
    ("  PLMN-PLMN/RNC-521/WBTS-176/WCEL-1", TEXT),
    ("  class NOKRNC:WCEL — read via CM API", FAINT),
    ("", MUTED),
    ("Huawei (4G cell):", CRIT),
    ("  LST CELL: LOCALCELLID=1;", TEXT),
    ("  MOD CELLALGOSWITCH: … ;", TEXT),
    ("  MML over U2020 — parsed to same table", FAINT),
    ("", MUTED),
    ("→ same grid in the UI, vendor hidden", GOLD),
]
yy = 1.92
for t, c in dn:
    text(s, rx + 0.3, yy, rw - 0.55, 0.3, [[(t, 11.5, c, False, MONO)]])
    yy += 0.3
text(s, rx, 5.0, rw, 0.5,
     [[("Exports land as Excel — the same file format the mass-modify flow re-imports.", 10.5, FAINT, False, FONT, True)]])
footer(s, "06 · CM")
demo_cue(s, 5.62,
         "Extract one site's cells; open the Excel; look up one parameter in the dictionary.",
         "Configuration → Configuration Data Extractor → site scope → Extract  ·  Parameter Dictionary")

# ============================================================ 13 · AUDIT & CHANGE IMPACT
s = slide_base()
header(s, "Section 07", "CM Parameter Audit & Change Impact")
# left: audit
rect(s, 0.55, 1.4, 6.05, 4.15, fill=PANEL, line=ACCENT, line_w=1.25, radius=0.05)
text(s, 0.82, 1.55, 5.5, 0.3, [[("GOLDEN-PARAMETER AUDIT", 12.5, ACCENT, True)]])
text(s, 0.82, 1.9, 5.55, 0.65,
     [[("You define the golden config as rules; the tool scans the latest CM snapshot and flags every violation.", 11, MUTED, False)]])
rules = [
    ("equals", "value must match expected (e.g. qRxLevMin = -128)", TEAL),
    ("range", "numeric bounds (e.g. 0 ≤ tilt offset ≤ 10)", GOLD),
    ("not_empty", "parameter must be set at all", PURPLE),
]
yy = 2.6
for rt, d, col in rules:
    rect(s, 0.82, yy, 5.5, 0.55, fill=CODEBG, line=BORDER, radius=0.05)
    text(s, 1.0, yy + 0.05, 1.5, 0.45, [[(rt, 11, col, True, MONO)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 2.5, yy + 0.05, 3.75, 0.45, [[(d, 9.5, MUTED, False)]], anchor=MSO_ANCHOR.MIDDLE)
    yy += 0.63
text(s, 0.82, yy + 0.02, 5.5, 0.9,
     [[("Rules carry vendor / RAT / MO-class scope and their own severity (Critical→90 … Low→30). Findings export to Excel for the change board.", 10.5, MUTED, False)]])
# right: change impact
rect(s, 6.75, 1.4, 6.0, 4.15, fill=PANEL, line=CRIT, line_w=1.25, radius=0.05)
text(s, 7.02, 1.55, 5.5, 0.3, [[("CHANGE IMPACT TRACKER", 12.5, CRIT, True)]])
text(s, 7.02, 1.9, 5.5, 0.65,
     [[("Answers the morning-after question: did yesterday's parameter changes hurt anything?", 11, MUTED, False)]])
steps = [
    ("1", "Diff CM snapshots → list of parameter changes per cell"),
    ("2", "Pull the degraded-cells list from daily PM (accessibility, retainability…)"),
    ("3", "Correlate: change + degradation on the same cell → score 65; change alone → 35"),
    ("4", "Summary names both: \"pci changed 101→237. PM degradation also seen in Retainability (−4.2%)\""),
]
yy = 2.6
for n, d in steps:
    text(s, 7.02, yy, 5.5, 0.65,
         [[(n + "  ", 12, CRIT, True, MONO), (d, 10.5, MUTED, False)]], line_spacing=1.05)
    yy += 0.72
footer(s, "07 · Audit & impact")
demo_cue(s, 5.72,
         "Run the audit on one vendor/RAT; then show a correlated change in Change Impact.",
         "Configuration → CM Parameter Audit → Scan  ·  Radio Optimization → Change Impact Tracker")

# ============================================================ 14 · RET
s = slide_base()
header(s, "Section 07", "RET: reading & changing tilts safely", kicker_color=GOLD)
bullets(s, 0.55, 1.4, 6.05, 3.6, [
    ("Read tilts across both vendors ", "in one grid — current electrical tilt per antenna/RET unit, joined to cell & site metadata."),
    ("Writes are explicit, never bulk-blind. ", "You stage the target tilt per RET unit; the tool generates the vendor command (Huawei RET MOD / Nokia CM write)."),
    ("Value handling is vendor-aware. ", "Tilt units, offsets, and command formatting differ per vendor — the tool normalizes so you type degrees, not vendor syntax."),
    ("Every applied change is recorded ", "in Config History: what, when, who, old → new — your rollback reference."),
    ("Close the loop with Change Impact: ", "tomorrow, the tilt change shows up correlated with its KPI effect."),
], size=12, gap=8)
# right: tilt workflow
rx, rw = 6.9, 5.85
rect(s, rx, 1.4, rw, 3.55, fill=CODEBG, line=GOLD, line_w=1.0, radius=0.04)
text(s, rx + 0.28, 1.55, rw - 0.5, 0.3, [[("TILT CHANGE — TYPICAL FLOW", 11, GOLD, True)]])
flow = [
    ("1  Detect", "overshooting candidate at 14 km, azimuth 120°", ACCENT),
    ("2  Confirm", "map geometry + HO evidence + (TA if available)", TEAL),
    ("3  Read", "current tilt: 2° electrical on that RET unit", PURPLE),
    ("4  Stage", "target 4° — review generated command", GOLD),
    ("5  Apply", "execute; result logged to Config History", ORANGE),
    ("6  Verify", "next-day Change Impact + neighbor HO SR", CRIT),
]
yy = 2.0
for t, d, col in flow:
    rect(s, rx + 0.3, yy, 0.16, 0.16, fill=col, shape=MSO_SHAPE.OVAL)
    text(s, rx + 0.6, yy - 0.05, rw - 0.9, 0.3,
         [[(t, 11.5, TEXT, True), ("   " + d, 10.5, MUTED, False)]])
    if col != CRIT:
        line(s, rx + 0.38, yy + 0.2, rx + 0.38, yy + 0.42, color=BORDER, w=1.0)
    yy += 0.47
footer(s, "07 · RET")
demo_cue(s, 5.62,
         "Read tilts for one site; stage (but don't apply) a change and show the generated command.",
         "Configuration → RET Management → site filter",
         watch="The vendor command preview — degrees in, vendor syntax out.")

# ============================================================ 15 · DAILY LOOP
s = slide_base()
header(s, "Section 08", "The daily loop: morning report & sector health")
# left: morning report
rect(s, 0.55, 1.4, 6.05, 3.05, fill=PANEL, line=ORANGE, line_w=1.25, radius=0.05)
text(s, 0.82, 1.55, 5.5, 0.3, [[("RADIO MORNING REPORT", 12.5, ORANGE, True)]])
bullets(s, 0.82, 1.95, 5.55, 2.3, [
    ("One overnight roll-up ", "of every detection: sleeping cells, hotspots, neighbor issues, audit failures."),
    ("Ranked by severity ", "so the first 15 minutes of the day are triage, not hunting."),
    ("Each line links back ", "to its source module with evidence intact."),
], size=11.5, gap=6)
# right: sector health
rect(s, 6.75, 1.4, 6.0, 3.05, fill=PANEL, line=TEAL, line_w=1.25, radius=0.05)
text(s, 7.02, 1.55, 5.5, 0.3, [[("SECTOR HEALTH MONITOR", 12.5, TEAL, True)]])
bullets(s, 7.02, 1.95, 5.5, 2.3, [
    ("Per-sector KPI composite ", "across accessibility, retainability, mobility, interference."),
    ("All-cells variant ", "covers the whole network, with site names derived from cell names."),
    ("Your drill-down surface ", "when a report line needs context: is it one cell or the whole sector?"),
], size=11.5, gap=6, lead=TEAL)
text(s, 0.55, 4.62, 12.2, 0.5,
     [[("Trusting the numbers:  ", 12, TEAL, True),
       ("data freshness is visible (per-vendor last-loaded day), missing days are shown as missing, and no KPI is ever interpolated. If the report looks quiet, check freshness before celebrating.", 12, MUTED, False)]])
footer(s, "08 · Daily loop")
demo_cue(s, 5.55,
         "Open the morning report; follow one Critical line to its module and evidence.",
         "Radio Optimization → Radio Morning Report → click a finding")

# ============================================================ 16 · RUNBOOK
s = slide_base(divider=True)
constellation(s, n=40, seed=3, link=1.7)
rect(s, 0.55, 0.5, 0.09, 0.62, fill=GOLD, shape=MSO_SHAPE.RECTANGLE)
text(s, 0.78, 0.46, 11.8, 0.3, [[("APPENDIX", 11, GOLD, True)]])
text(s, 0.77, 0.7, 12.0, 0.6, [[("End-to-end demo runbook (the full loop, live)", 25, TEXT, True, FONT_L)]])
run = [
    ("Morning Report", "Start where the day starts — ranked overnight findings.", "Triage"),
    ("Sleeping Cells", "Drill into a Critical: recent[] vs baseline[] evidence.", "Detection logic"),
    ("Performance Explorer", "Trend the same cell's traffic KPI to confirm the flatline.", "KPI verification"),
    ("Overshooting → Map", "Pick a candidate; check azimuth & distance geometry.", "Diagnosis"),
    ("RET Management", "Read the tilt; stage the fix; show the vendor command.", "Change (staged)"),
    ("CM Parameter Audit", "Scan the same area against golden rules.", "Config hygiene"),
    ("Change Impact", "Show yesterday's changes correlated with PM deltas.", "Verification"),
]
yy = 1.55
for i, (t, d, why) in enumerate(run):
    rect(s, 0.55, yy, 12.2, 0.66, fill=RGBColor(0x14, 0x1E, 0x2B), line=BORDER, radius=0.05)
    rect(s, 0.55, yy, 0.5, 0.66, fill=GOLD, shape=MSO_SHAPE.RECTANGLE)
    text(s, 0.55, yy, 0.5, 0.66, [[(str(i + 1), 18, BG, True, FONT_L)]], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 1.2, yy, 3.1, 0.66, [[(t, 12.5, TEXT, True)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 4.35, yy, 5.0, 0.66, [[(d, 11, MUTED, False)]], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 9.45, yy, 3.15, 0.66, [[("↳ " + why, 10.5, TEAL, False, FONT, True)]], anchor=MSO_ANCHOR.MIDDLE)
    yy += 0.72
text(s, 0.55, yy + 0.02, 12.2, 0.3,
     [[("≈ 20 minutes at demo pace. Steps 1–4 are safe anywhere; steps 5–7 stage changes only — nothing is applied during the demo.", 11, FAINT, False, FONT, True)]])

# ============================================================ 17 · CLOSE
s = slide_base(divider=True)
constellation(s, n=64, seed=11, link=2.0)
text(s, 0.9, 2.1, 11.5, 0.4, [[("TAKEAWAYS", 14, ACCENT, True)]])
text(s, 0.85, 2.5, 11.6, 1.0, [[("Evidence in, action out", 44, WHITE, True, FONT_L)]])
bullets(s, 0.9, 3.75, 11.5, 2.2, [
    ("Every detection is explainable ", "— fixed formulas, visible thresholds, raw KPI evidence on every issue card."),
    ("Two vendors disappear ", "— KPI recipes and CM adapters give you one workflow across Nokia and Huawei, 2G–5G."),
    ("The loop closes ", "— detect → diagnose → staged change → next-day impact, with Config History as the audit trail."),
    ("Nothing is interpolated, nothing writes blind ", "— missing data shows as missing; changes stage before they apply."),
], size=13, gap=8)
rect(s, 0.9, 6.15, 11.5, 0.7, fill=RGBColor(0x14, 0x1E, 0x2B), line=GOLD, line_w=1.0, radius=0.06)
text(s, 0.9, 6.15, 11.5, 0.7,
     [[("Questions?  ", 14, GOLD, True), ("Name a site — let's run the loop on it live.", 13, TEXT, False)]],
     align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

out = "/home/user/PrimeNet/PrimeNet_Engineering_DeepDive.pptx"
prs.save(out)
print("saved", out, "slides:", len(prs.slides._sldIdLst))
