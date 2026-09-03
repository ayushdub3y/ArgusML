---
name: Obsidian Sentinel
colors:
  surface: '#0f131c'
  surface-dim: '#0f131c'
  surface-bright: '#353942'
  surface-container-lowest: '#0a0e16'
  surface-container-low: '#181c24'
  surface-container: '#1c2028'
  surface-container-high: '#262a33'
  surface-container-highest: '#31353e'
  on-surface: '#dfe2ee'
  on-surface-variant: '#bdc8d1'
  inverse-surface: '#dfe2ee'
  inverse-on-surface: '#2c3039'
  outline: '#87929a'
  outline-variant: '#3e484f'
  surface-tint: '#7bd0ff'
  primary: '#8ed5ff'
  on-primary: '#00354a'
  primary-container: '#38bdf8'
  on-primary-container: '#004965'
  inverse-primary: '#00668a'
  secondary: '#4edea3'
  on-secondary: '#003824'
  secondary-container: '#00a572'
  on-secondary-container: '#00311f'
  tertiary: '#c7c8ff'
  on-tertiary: '#1000a9'
  tertiary-container: '#a7a9ff'
  on-tertiary-container: '#2b29bb'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#c4e7ff'
  primary-fixed-dim: '#7bd0ff'
  on-primary-fixed: '#001e2c'
  on-primary-fixed-variant: '#004c69'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#e1e0ff'
  tertiary-fixed-dim: '#c0c1ff'
  on-tertiary-fixed: '#07006c'
  on-tertiary-fixed-variant: '#2f2ebe'
  background: '#0f131c'
  on-background: '#dfe2ee'
  surface-variant: '#31353e'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-code-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.02em
  metric-val-lg:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 26px
    letterSpacing: -0.02em
  metric-sub-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  compact-xs: 0.25rem
  compact-sm: 0.5rem
  compact-md: 0.75rem
  compact-lg: 1rem
  section-gap: 1.5rem
  grid-gutter: 1rem
  table-row-h: 2.25rem
  table-cell-px: 0.75rem
---

## Brand & Style

This design system targets high-velocity FinTech operations, fraud defense command centers, and automated SecOps environments. The interface must evoke absolute operational clarity, mathematical certainty, and calm control under mission-critical latency.

The aesthetic blends **Minimalism** and **High-Density Technical Functionalism**:
- Deep obsidian backdrop layers prevent eye fatigue during prolonged shifts.
- Structural hairline borders establish razor-sharp visual containment without decorative overhead.
- High-contrast typography pairs neutral grotesque headers and UI labels with precise monospace engineering telemetry.
- Semantic indicators act purely as signaling beacons: vibrant status hues are deployed solely to flag state transitions, model drift, SLAs, and security triggers.

## Colors

The palette is engineered around dark light-absorption surfaces and high-signal alert channels:

### Backgrounds & Surfaces
- **Canvas Base (`#0B0F17`):** Primary viewport backdrop; unyielding obsidian.
- **Card Surface (`#111827`):** Primary structural surface for telemetry tiles, queue tables, and logs.
- **Elevated Interactive Surface (`#1A2234`):** Hover states, active table rows, and modal dialogues.

### Borders & Dividing Lines
- **Hairline Border (`#1E293B`):** Baseline container separation and inner card borders.
- **Focus / Active Rule Border (`#334155`):** Structural table headers, input boundaries, and divider strokes.

### Operational Accents & Status Semantics
- **Model Telemetry & Adjudication (`#38BDF8` / `#6366F1`):** Applied to algorithmic probabilities, LLM evidence pipelines, and engine telemetry.
- **Operational Health / Accept (`#10B981`):** Applied to active defense status, positive adjudications, and valid checksums.
- **Pending Review / Human Checkpoint (`#F59E0B`):** Applied to mandatory verification queues, manual reviews, and drift alerts.
- **Critical Risk / Escalation (`#EF4444`):** Applied to SLA breaches, velocity violations, and immediate escalation flags.

Text layers utilize strict contrast steps: Primary `#F8FAFC`, Muted `#94A3B8`, and Ghost/Timestamp `#64748B`.

## Typography

Typography enforces a strict dichotomy between human-readable contextual information and machine data:
- **Inter** is designated for top-level headers, descriptive copy, queue section names, and action buttons to deliver neutral legibility at high information density.
- **JetBrains Mono** is mandatory for system telemetry, dispute hashes, currency units, risk probabilities ($p=0.00$), rule names, timestamps, and model names.

Upper-case tracking (`letter-spacing: 0.05em`) is enforced on micro metadata labels (e.g., `MODEL A ADJUDICATOR`, `SLA COUNTDOWN`) at 10px–11px sizing to ensure crisp optical rendering on high-DPI displays.

## Layout & Spacing

The layout model is anchored by a high-density, 12-column responsive fluid grid designed for 1440px+ command displays with safe scaling down to mobile viewports:

- **Telemetry Bar:** 4-column metric cards across standard viewports, collapsing to 2 columns on tablet (`<1024px`) and 1 column on mobile (`<640px`).
- **Data Tables & Queues:** Span 12 full columns with fixed-height rows (36px–40px) to maximize screen real estate and row scan efficiency.
- **Rhythm & Padding:** Outer page margin is set to `1.5rem` (24px). Internal card padding maintains a compact `1rem` (16px) bounding box. Table cells utilize vertical padding of `0.5rem` (8px) and horizontal padding of `0.75rem` (12px).

## Elevation & Depth

This system intentionally rejects heavy drop shadows, gradients, and blurred drop effects in favor of flat **Tonal Layering** and **Hairline Outlines**:

- **Layer 0 (Canvas Base):** Ground level (`#0B0F17`).
- **Layer 1 (Cards & Data Panels):** `#111827` encapsulated by a 1px uniform hairline border (`#1E293B`).
- **Layer 2 (Interactive Row Hover & Flyouts):** `#1A2234` with high-contrast perimeter (`#334155`).
- **Active Signaling Glows:** Transient, high-priority system alerts (e.g., live engine status or SLA warnings) may use a constrained 4px–8px ambient glow tinted to the semantic state (`rgba(16, 185, 129, 0.25)` or `rgba(239, 68, 68, 0.25)`).

## Shapes

The design language favors crisp, disciplined, low-radius geometry to reinforce an industrial terminal character:
- Standard containers, metric panels, and table wraps implement `0.375rem` (6px) corner rounding.
- Badges, status chips, and code tags employ `0.25rem` (4px) corner rounding.
- Pill shapes (`9999px`) are strictly reserved for top-level operational status badges (e.g., `● Live` status indicators).

## Components

### Metric & Telemetry Tiles
- Encased in `#111827` with a 1px `#1E293B` perimeter.
- Top label: 11px uppercase `JetBrains Mono` in muted `#94A3B8`.
- Primary value: 20px `Inter` bold in `#F8FAFC` alongside semantic performance pills.
- Bottom subtext: 11px `JetBrains Mono` in `#64748B` displaying timestamps and run IDs.

### Data Tables & Queue Strips
- Table headers: `#111827` background, uppercase 11px `JetBrains Mono`, separated by a 1px `#1E293B` bottom border.
- Rows: 36px default height, transition to `#1A2234` on pointer hover.
- Identifiers: Enclosed in a compact code chip with `#1A2234` fill and `#334155` border.

### Status Chips & Telemetry Badges
- **Accept / Active:** `#064E3B` fill (20% opacity), `#10B981` text, 1px `#059669` hairline border.
- **Review / Pending:** `#78350F` fill (20% opacity), `#F59E0B` text, 1px `#D97706` hairline border.
- **Critical Risk / Escalation:** `#7F1D1D` fill (25% opacity), `#EF4444` text, 1px `#DC2626` hairline border.
- **Model / Adjudicator:** `#0C4A6E` fill (25% opacity), `#38BDF8` text, 1px `#0284C7` hairline border.

### Primary & Action Buttons
- **Primary:** `#38BDF8` fill with `#0B0F17` bold typography for instant target recognition.
- **Destructive / Escalate:** `#EF4444` surface with high-contrast white text.
- **Ghost / Action Cell:** Transparent base, `#94A3B8` text, transitioning to `#1E293B` surface and `#F8FAFC` text on hover.

### Inputs & Filters
- Background `#0B0F17`, 1px border `#1E293B`, focus ring 1px `#38BDF8`. Text rendered in 12px `JetBrains Mono`.