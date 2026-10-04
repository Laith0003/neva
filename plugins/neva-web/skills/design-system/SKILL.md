---
name: design-system
description: "Extract a design system from an existing codebase (tokens, DESIGN.md, preview page) or audit UI for visual consistency across 10 scored dimensions plus AI-slop checks. Use when starting a design system, auditing before a redesign, or reviewing a styling PR."
metadata:
  origin: affaan-m/ECC (MIT), adapted for Neva
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Derive-from-shipped and bidirectional token guidance from Neva house practice; engine pointer to ux-skill (MIT). -->

# Design System: Generate and Audit Visual Systems

## First Rule

If the project already has a design system, this skill documents and audits it. It never replaces it. Tokens, components, and naming that exist win over anything proposed here. Extend, do not fork.

For a full engine (styles, palettes, type pairings, component contracts, motion presets, deterministic lint), the recommended companion is the `ux-skill` plugin (MIT, PyPI `uxskill`), whose `/ux-system` command builds complete token sets. This skill is the lightweight, dependency-free path.

## When to Use

- Starting a new project that needs a design system
- Auditing an existing codebase for visual consistency
- Before a redesign: understand what you have
- When the UI looks off and you cannot say why
- Reviewing PRs that touch styling

## How It Works

### Mode 1: Generate (derive from what shipped)

Derive the system from the code and rendered UI, not from intentions:

```
1. Scan CSS, Tailwind config and @theme, CSS variables, styled-components, Blade/Vue/JSX class usage
2. Extract: colors, typography, spacing, radius, shadows, breakpoints, z-index, motion durations and easings
3. Cluster near-duplicates (e.g. #111, #121212, #0f0f0f) and propose one token per cluster with every usage site
4. Optionally study 2 or 3 reference products in the same domain (browser tools) for calibration, never to copy
5. Propose a token set: design-tokens.json + CSS custom properties, semantic names over raw names
6. Write DESIGN.md with the rationale for each decision and the migration map (old value -> token)
7. Create a self-contained HTML preview page (no dependencies) that renders every token, in light and dark, LTR and RTL
```

Output: `DESIGN.md` + `design-tokens.json` + `design-preview.html`

Token rules:

- Two layers: primitives (`--gray-900`) and semantic aliases (`--color-text`, `--color-surface-raised`). Components consume only semantic tokens.
- Spacing and sizing tokens are direction-agnostic; components apply them through logical properties (`padding-inline`, `margin-block`), so one token set serves LTR and RTL.
- Type tokens carry per-script settings where needed: Arabic and other connected scripts get their own family, larger line-height, and zero letter-spacing.
- Dark mode is a token remap, not a second stylesheet. Test both before finishing.
- Motion tokens: a small set of durations and easings, plus a reduced-motion override.

### Mode 2: Visual Audit

Score the UI across 10 dimensions (0 to 10 each):

```
1. Color consistency: palette tokens or random hex values?
2. Typography hierarchy: clear h1 > h2 > h3 > body > caption, in every script?
3. Spacing rhythm: consistent scale (4/8/16) or arbitrary?
4. Component consistency: do similar elements look and behave the same?
5. Responsive behavior: fluid or broken at breakpoints?
6. Theming: dark mode complete or half-done? RTL mirrored or bolted on?
7. Animation: purposeful or gratuitous? Reduced motion respected?
8. Accessibility: contrast, focus states, target sizes
9. Information density: cluttered or clean for its audience?
10. Polish: hover, active, loading, empty, and error states present and designed
```

Each dimension gets a score, specific examples, and a fix with exact `file:line`.

### Mode 3: AI Slop Detection

Flag generic generated patterns:

```
- Gratuitous gradients; purple-to-blue defaults
- Glassmorphism with no purpose
- One radius and one shadow on everything
- Scroll-triggered animation on every section
- Centered hero over a stock gradient with generic CTA
- Default font stack with no reason; Inter at display size by habit
- All-caps eyebrow labels over every heading; arrows appended to every link
- Placeholder people and round fake metrics
- Physical left/right spacing that breaks in RTL
```

## Examples

**Generate for a SaaS app:**
```
/design-system generate --style minimal --palette earth-tones
```

**Audit existing UI:**
```
/design-system audit --url http://localhost:3000 --pages / /pricing /docs
```

**Check for AI slop:**
```
/design-system slop-check
```

## Verification

Render `design-preview.html` and at least one real page with the new tokens, take screenshots in light and dark (and RTL if the product supports it), and look at them before reporting done.
