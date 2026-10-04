---
name: frontend-design-direction
description: "Pick and hold a specific design direction before building or reshaping any web UI (page, dashboard, component, app). Use when UI must feel intentional rather than templated, or when a working UI reads generic."
metadata:
  origin: affaan-m/ECC (MIT), adapted for Neva
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Two-pass plan and calibration informed by anthropics frontend-design (Apache-2.0); audit-first redesign and brief inference informed by the open taste-skill set; RTL guidance from Neva house practice. -->

# Frontend Design Direction

Use this skill when the work is not just making UI function, but making it feel purposeful, polished, and specific to its subject. Original ECC guidance salvaged from community PR #1659 by `linus707`.

## Order of Authority

1. The project's own design system (tokens, `DESIGN.md`, component library, brand guide). If it exists, it is the brief. Follow it and only decide what it leaves open.
2. The user's brief, in their words. If it names a look, build that look exactly, even one listed under Calibration below.
3. This skill, for every axis the first two leave free.

For a full design engine (style, palette, type, motion presets, a deterministic anti-slop linter), the recommended companion is the `ux-skill` plugin (MIT, PyPI `uxskill`). For a pure aesthetic exploration, the official `frontend-design` skill from anthropics is a good pairing. This skill stays generic and defers to both.

## When to Use

- Building a web page, app, dashboard, artifact, component, or UI.
- Making an interface more polished, distinctive, or less generic.
- The implementation needs hierarchy, typography, color, motion, layout, and interaction choices.
- The current UI works but reads flat, templated, or mismatched to its audience.

## Step 0: Read the Brief (one line out loud)

Before any code, write a one-line design read:

`Subject: ... | Audience: ... | Primary job: ... | Tone: ... | Density: ... | Direction: LTR, RTL, or both`

- If the brief does not name the subject, propose one concrete subject, audience, and job, and confirm.
- If one axis is truly ambiguous and changes the outcome, ask one question. Do not guess, do not ask five.
- Existing product: detect it first. A redesign is audit-first (see Redesign below), not a fresh canvas.

## Step 1: Choose a Direction

1. Purpose: what job does the interface do?
2. Audience: who repeats this workflow, and what do they scan first?
3. Tone: utilitarian, editorial, playful, industrial, refined, technical, maximal, minimal, dense, calm, or another explicit word.
4. Memorable detail: one design idea that makes the result feel intentional. Spend boldness in one place and keep everything around it quiet.
5. Constraints: framework, accessibility, performance, responsiveness, reading direction, scripts to support, existing design system.

Match the direction to the domain. An operations tool should usually be dense, quiet, and scannable. A portfolio, launch page, game, or editorial piece can be more expressive. Do not force a landing-page composition onto a tool used daily. Distinctive choices come from the subject's own world: its materials, vernacular, and artifacts.

## Step 2: Two-Pass Plan, Then Build

Pass one, write a compact plan:

- Color: 4 to 6 named values with roles (surface, text, muted, accent, state colors).
- Type: one or two families with roles and a clear scale. If two, make them clearly distinct. Every script the product renders (Arabic, Latin, CJK) needs a face with real coverage and matching weights.
- Layout: one-sentence concept plus an ASCII wireframe; say how content aligns.
- Principles: two or three rules that make this surface unlike its neighbors.

Pass two, review the plan against the brief. For each part ask: would I arrive here for any similar brief? If yes, it is a default, not a choice. Revise it and say what changed and why. Only then write code.

## Implementation Guidance

- Build the usable experience as the first screen unless the user asked for marketing.
- Use existing project components, tokens, icons, and routing before introducing anything new.
- Use real or generated assets when the interface depends on images, products, places, people, charts, or media.
- Typography carries personality: set a real scale, keep line length under about 80 characters, give serif and Arabic body text more line-height, never letter-space Arabic.
- Keep palettes multi-dimensional; avoid a UI dominated by one hue family.
- Put every value in CSS variables or existing tokens so states stay coherent.
- Design responsive constraints explicitly: grids, aspect ratios, min and max sizes; toolbars and fixed-format controls must not shift when labels or hover states change.
- Build bidirectional from the start: logical properties (`margin-inline-start`, Tailwind `ms-*`/`pe-*`/`start-*`), `dir` on `<html>`, mirrored directional icons, LTR islands for numbers and codes.
- Motion: one orchestrated moment beats scattered effects. Motion that answers a user action (open, expand, confirm) is welcome when it shows what changed. Respect reduced motion.
- Watch CSS specificity: section-level and element-level selectors that cancel each other out are a common cause of broken spacing.
- Verify text fit on mobile and desktop, in the longest locale. Long labels wrap or resize cleanly.

## Calibration: Defaults That Read as Generated

Legitimate when the brief asks. Otherwise do not spend free axes on them:

- Warm cream background, high-contrast serif, one terracotta or clay accent.
- Near-black background with one acid-green or vermilion accent.
- Broadsheet layout with hairline rules, zero radius, dense columns, on a subject that is not editorial.
- The SaaS card kit: identical rounded cards, one radius everywhere, the same soft grey shadow, gradient washes.
- Template chrome: tracked all-caps eyebrow over every heading, `A · B · C` meta strings, labels built as `WORD, fragment` with a spaced dash, tinted near-black standing in for black, monospace for small labels, an arrow appended to every link.
- A big number with a small label and a gradient accent as the default hero.
- One word in a headline set in italic or a different color.
- Numbered markers (01, 02, 03) on content that is not a sequence.
- Fade-and-slide-up on every section, hover lift on every card.
- Purple-to-blue gradients, decorative blobs, stock atmospheric media, placeholder people named "Jane Doe", round fake metrics.

## Anti-Patterns

- Cards inside cards.
- One decorative style everywhere when the domain calls for restraint.
- Hiding the primary product, tool, or workflow behind generic marketing sections.
- Adding a dependency for a flourish that does not pay for itself.
- Describing the UI's features inside the UI when the controls can speak.
- Copy that sells instead of explains. Name things by what users understand, keep an action's name stable through the flow ("Publish" produces "Published"), and make errors say what happened and how to fix it.

## Redesign Protocol (existing product)

1. Scan: framework, styling method, tokens, component library, current patterns.
2. Audit before touching: list generic patterns, weak hierarchy, missing states (hover, focus, active, loading, empty, error), broken RTL, contrast failures.
3. Preserve: routes, data flow, copy meaning, brand assets, accessibility wins. Nothing changes silently.
4. Decide: targeted evolution (tokens, type, spacing, states) when the structure is sound; full redesign only when the structure itself fails the job, and say so first.
5. Fix inside the existing stack. Do not rewrite from scratch to change a look.

## Review Checklist

- The first viewport communicates the product, workflow, or object.
- Hierarchy supports scanning and repeated use.
- Typography fits its container and does not collide with neighbors, in every locale.
- Color has contrast and does not collapse into a one-note palette.
- Familiar tool actions use icons; directional icons mirror in RTL.
- Boards, grids, toolbars, controls, tiles, and counters keep stable dimensions.
- Assets render and carry the subject instead of acting as filler.
- Motion improves orientation and does not mask sluggishness.
- Keyboard focus is visible, reduced motion is respected.
- The result matches the repo's frontend conventions unless there is a stated reason to depart.
- You rendered it and looked at a screenshot, in both directions if the product is bidirectional.
