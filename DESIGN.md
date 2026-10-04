---
name: NexusCore
description: Ops Constellation — cinematic portal gate, soft-steel engineering workbench
colors:
  soft-steel-sky: "#4f8db8"
  soft-steel-sky-deep: "#3a7399"
  header-mist: "#8fb9d4"
  header-mid: "#5f9bc0"
  cool-paper: "#e8eef4"
  surface: "#ffffff"
  surface-elevated: "#f4f6f8"
  surface-tint: "#dceaf4"
  ink: "#2c3e50"
  ink-muted: "#5c6773"
  ink-muted-soft: "#7f8c8d"
  border-cool: "#9ec0d8"
  border-neutral: "#dde1e6"
  dm-bg: "#0f1722"
  dm-panel: "#182230"
  dm-panel-2: "#1b2736"
  dm-panel-3: "#223246"
  dm-border: "#304258"
  dm-text: "#e8eef7"
  dm-muted: "#a9b7c9"
  dm-link: "#8bc1ff"
  dm-input: "#101b28"
  gate-navy-0: "#020617"
  gate-navy-1: "#061336"
  gate-cyan: "#38bdf8"
  gate-cyan-soft: "#7dd3fc"
  gate-ink: "#e2eeff"
  gate-muted: "#8fb3dd"
  success: "#27ae60"
  secondary: "#95a5a6"
typography:
  display:
    fontFamily: "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"
    fontSize: "2.5em"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "normal"
  headline:
    fontFamily: "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"
    fontSize: "1.55em"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "normal"
  title:
    fontFamily: "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"
    fontSize: "1.05em"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "normal"
  body:
    fontFamily: "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"
    fontSize: "1em"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"
    fontSize: "0.85em"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
rounded:
  sm: "5px"
  md: "7px"
  lg: "8px"
  xl: "12px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "20px"
  xl: "40px"
  main-x: "60px"
components:
  button-primary:
    backgroundColor: "{colors.soft-steel-sky}"
    textColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "12px 30px"
    typography: "{typography.title}"
  button-primary-hover:
    backgroundColor: "{colors.soft-steel-sky-deep}"
    textColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "12px 30px"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "10px 20px"
  button-header:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.soft-steel-sky-deep}"
    rounded: "{rounded.md}"
    padding: "7px 14px"
  button-header-outline:
    backgroundColor: "rgba(255, 255, 255, 0.15)"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "7px 14px"
  card-surface:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xl}"
    padding: "20px 24px"
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "10px 14px"
---

# Design System: NexusCore

## Overview

**Creative North Star: "The Ops Constellation"**

NexusCore’s visual world is a dual-register operator platform. At the gate — login and the portal tower — the experience is cinematic: deep navy fields, constellation/radar atmosphere, soft cyan instrument light, and glass panels that feel like entering a control constellation. Once inside PrimeNet (and sibling portals’ work surfaces), the register shifts to a soft-steel daylight workbench: cool paper backgrounds, white instrument cards, clear steel accents (not washed pastels), and scan-first density for RAN engineers.

Personality is tactile instrument chrome — controls should feel pressable and precise, not decorative. Soft lift keeps cards and panels slightly airborne so structure reads quickly without heavy skeuomorphism. The system rejects purple SaaS gradients and neon cyber glow; accent energy stays in Soft Steel Sky and gate cyan only.

**Key Characteristics:**
- Dual-register: cinematic gate → utilitarian engineering floors
- Soft Steel Sky as the sole primary accent family in work surfaces
- Soft-lift cards/panels with cool borders and restrained shadows
- System UI type (Segoe stack) for operator familiarity and speed
- Light + dark parity required; dark uses slate-navy tonal panels (`--dm-*`)

## Colors

Cool steel-blue instrument palette with a deeper navy/cyan gate register; neutrals stay paper-cool, never warm cream.

### Primary
- **Soft Steel Sky** (`#4f8db8`): Primary actions, header terminus, workbench accents. Clearer chroma than the earlier washed pastel — still cool, not neon.
- **Soft Steel Sky Deep** (`#3a7399`): Primary hover, header button ink, light-mode ribbons.
- **Header Mist → Mid** (`#8fb9d4` → `#5f9bc0`): Light-mode header gradient with Soft Steel Sky.

### Secondary
- **Instrument Gray** (`#95a5a6`): Secondary buttons and de-emphasized actions.
- **Signal Green** (`#27ae60`): Success / confirm actions only — not brand chrome.

### Tertiary
- **Gate Cyan** (`#38bdf8`) / **Gate Cyan Soft** (`#7dd3fc`): Login and portal-tower atmosphere only. Do not flood PrimeNet module pages with cyan neon.

### Neutral
- **Cool Paper** (`#e8eef4`): Light page / main canvas.
- **Surface** (`#ffffff`) / **Surface Elevated** (`#f4f6f8`) / **Surface Tint** (`#dceaf4`): Cards, toolbars, subtle strips.
- **Ink** (`#2c3e50`) / **Ink Muted** (`#5c6773`, `#7f8c8d`): Body and captions.
- **Border Cool / Neutral** (`#9ec0d8`, `#dde1e6`): Card and input edges.
- **Dark slate navy** (`#0f1722` bg, `#182230` / `#1b2736` / `#223246` panels, `#304258` border, `#e8eef7` text, `#a9b7c9` muted, `#8bc1ff` links, `#101b28` inputs): Canonical `body.dark-mode` tokens.
- **Gate navy** (`#020617`, `#061336`) with gate ink/muted: Lobby and login shells.

### Named Rules
**The Soft Steel Sky Rule.** Workbench accent is Soft Steel Sky (and its deep twin). Do not introduce a second brand accent on module pages.

**The Gate Cyan Containment Rule.** Gate cyan belongs to login/portal-tower atmosphere. Inside Engineering modules, steel + dark-link blue carry interaction — not neon cyan wash.

**The No Purple Nebula Rule.** No purple/magenta SaaS gradients, no fuchsia cyber glow rings. If atmosphere needs energy, use steel or gate cyan only.

## Typography

**Display Font:** Segoe UI (with Tahoma, Geneva, Verdana)
**Body Font:** Segoe UI (same stack)
**Label/Mono Font:** Consolas / SFMono / Menlo for telemetry-style labels on gate surfaces only

**Character:** Familiar Windows-operator UI type — clear, dense, unpretentious. Hierarchy comes from weight and size, not display serifs.

### Hierarchy
- **Display** (600, ~2.5em): Dashboard / deck hero titles.
- **Headline** (600, ~1.55em): Module header titles.
- **Title** (600, ~1.05em): Section and card titles; button weight cue.
- **Body** (400, 1em, ~1.5 line-height): Tables, forms, explanatory copy.
- **Label** (600, ~0.85em): Chips, header controls, filter captions.

### Named Rules
**The One Stack Rule.** Stay on the Segoe UI system stack for product chrome. Do not swap in Inter/Roboto/display serifs for “modern SaaS.”

## Layout

Workbench pages use a full-width column shell: shared header, then `.main-content` padded roughly `40px 60px` with a practical max width near `1400px`. Density is operator-grade — toolbars, filter strips, and tables sit close; spacing steps cluster around 4 / 8 / 14 / 20 / 40px. Global UI zoom (`--ui-zoom: 0.67`) is an incumbent layout contract for filling the window at an ops-friendly scale — new surfaces should assume this chrome exists rather than fighting it.

Responsive behavior tightens header padding and stacks header clusters below ~768px; keep critical actions reachable without hiding them behind mystery icons.

Dashboard/constellation decks use larger card radii (~12px) and floating navigation chrome; module pages stay closer to 8px instrument panels.

### Named Rules
**The Workbench Width Rule.** Prefer the shared main-content rail over edge-to-edge marketing layouts inside Engineering tools.

## Elevation & Depth

Soft lift: cards, panels, and key chrome float lightly via modest shadows and tonal steps. Light mode uses soft ambient shadows on headers and elevated cards (`0 4px 15px rgba(0,0,0,0.1)`, card lifts around `0 2px 12px` / `0 8px 24px` for floating chrome). Dark mode relies more on slate panel steps (`--dm-panel` → `--dm-panel-3`) with cooler, quieter lifts. Primary buttons lift on hover (`translateY(-2px)` + steel-tinted shadow).

Gate surfaces may use deeper glass shadows and blur; workbench surfaces should not copy that drama.

### Shadow Vocabulary
- **Header ambient** (`box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1)`): Shared top bar.
- **Card soft lift** (`0 2px 12px rgba(0, 0, 0, 0.12)`): Module/dashboard cards at rest.
- **Floating chrome** (`0 8px 24px rgba(44, 62, 80, 0.16)`): Deck FABs / elevated nav chips.
- **Primary hover** (`0 4px 12px rgba(79, 141, 184, 0.35)`): Affordance on primary actions.

### Named Rules
**The Soft Lift Rule.** Surfaces feel slightly airborne by default; reserve deep cinematic shadows for the gate register.

## Shapes

Gently curved instrument geometry: header chips ~7px, primary controls ~8px, dashboard cards ~12px, occasional full pills (`999px`) for theme toggles and deck chips. Borders are cool and visible — soft lift does not replace structure with shadow alone. Gate auth cards use larger radii (~14–18px) and glass blur; keep that silhouette at the gate.

### Named Rules
**The Instrument Corner Rule.** Prefer 7–12px radii for workbench chrome. Pill shapes are for chips/toggles, not primary form cards.

## Components

Tactile instrument chrome: controls should look pressable, labeled, and state-clear.

### Buttons
- **Shape:** Gently curved (`8px` primary; `7px` header chips; logout `5px`)
- **Primary:** Soft Steel Sky fill, white text, `12px 30px`, weight 600; hover deepens + lifts
- **Secondary:** Instrument gray fill
- **Header solid:** White chip, Soft Steel Sky Deep ink, `1.5px` white border
- **Header outline / back:** Translucent white on steel header gradient
- **Hover / Focus:** 0.2–0.3s color/border transitions; primary hover lift; keep focus visible (do not remove outlines without a stronger ring)

### Chips
- **Style:** Compact rounded rectangles or pills; cool borders; muted ink
- **State:** Selected states tint with Soft Steel Sky wash, not neon cyan on workbench pages

### Cards / Containers
- **Corner Style:** ~12px on dashboard cards; ~8px on many module panels
- **Background:** White / Cool Paper strips in light; `--dm-panel` family in dark
- **Shadow Strategy:** Soft lift (see Elevation)
- **Border:** Cool steel borders (`#9ec0d8` / `#dde1e6`; dark `#304258`)
- **Internal Padding:** Often ~20–24px; toolbars tighter

### Inputs / Fields
- **Style:** Light surface, cool border, ~8px radius
- **Focus:** Steel-tinted ring/glow (`rgba(79, 141, 184, …)`), not purple
- **Dark:** `--dm-input` fill and `--dm-border`

### Navigation
- Shared steel header gradient (dark: `#182533` → `#111924` family)
- Absolute left cluster (back / feature nav) and right user actions
- Dashboard constellation deck + floating feature nav as signature navigation theater
- Portal tower uses gate navy/cyan glass language

### Signature: Constellation / Portal Gate
Animated radar/starfield canvas behind lobby, login, and dashboard (`constellation` shell). This is the Ops Constellation signature — present at the gate and Engineering home, not mandatory behind every dense table module.

## Do's and Don'ts

### Do:
- **Do** keep the dual-register: cinematic gate, utilitarian modules.
- **Do** use Soft Steel Sky for primary workbench accent and honor `--dm-*` tokens in dark mode.
- **Do** soft-lift cards/panels and keep tactile, labeled controls.
- **Do** ship honest empty / not-connected states instead of decorative fake metrics chrome.
- **Do** load shared `common.css` + `common.js` so theme toggle and dark final cascade remain intact.

### Don't:
- **Don't** introduce purple/magenta SaaS gradients or neon cyber glow rings.
- **Don't** flood Engineering modules with gate-cyan neon atmospheres.
- **Don't** replace the Segoe system stack with trendy marketing type pairings.
- **Don't** invent a second primary brand color “to make it pop.”
- **Don't** hardcode light-only `#fff` / `#2c3e50` surfaces without `body.dark-mode` counterparts.
