---
paths:
  - "**/*.css"
  - "**/*.scss"
  - "**/*.sass"
  - "**/*.less"
  - "**/*.html"
  - "**/*.blade.php"
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.vue"
  - "**/*.svelte"
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Calibration list informed by anthropics frontend-design (Apache-2.0); engine pointer to ux-skill (MIT). -->
> This file extends [common/patterns.md](../common/patterns.md) with web-specific design-quality guidance.

# Web Design Quality Standards

## The Project's Design System Wins

If the project has a design system (tokens file, `DESIGN.md`, component library, Figma variables, a brand guide), it is the brief. Use its tokens, components, and voice. Everything below applies only to the axes the system leaves open. Never restyle an existing system to satisfy this file.

## Anti-Template Policy

Do not ship generic template-looking UI. Frontend output should look intentional, opinionated, and specific to the product.

### Banned Patterns

- Default card grids with uniform spacing and no hierarchy
- Stock hero section with centered headline, gradient blob, and generic CTA
- Unmodified library defaults passed off as finished design
- Flat layouts with no layering, depth, or motion
- Uniform radius, spacing, and shadows across every component
- Safe gray-on-white styling with one decorative accent color
- Dashboard-by-numbers layouts with sidebar + cards + charts and no point of view
- Default font stacks used without a deliberate reason

### Required Qualities

Every meaningful frontend surface should demonstrate at least four of these:

1. Clear hierarchy through scale contrast
2. Intentional rhythm in spacing, not uniform padding everywhere
3. Depth or layering through overlap, shadows, surfaces, or motion
4. Typography with character and a real pairing strategy
5. Color used semantically, not just decoratively
6. Hover, focus, and active states that feel designed
7. Grid-breaking editorial or bento composition where appropriate
8. Texture, grain, or atmosphere when it fits the visual direction
9. Motion that clarifies flow instead of distracting from it
10. Data visualization treated as part of the design system, not an afterthought

## Before Writing Frontend Code

1. Pick a specific style direction. Avoid vague defaults like "clean minimal".
2. Define a palette intentionally.
3. Choose typography deliberately.
4. Gather at least a small set of real references.
5. Use Neva design skills where relevant: `frontend-design-direction` to pick a direction, `design-system` to extract or audit tokens, `make-interfaces-feel-better` for the polish pass. For a full design engine (style, palette, type, motion presets, deterministic anti-slop lint), the recommended companion is the `ux-skill` plugin (MIT, PyPI `uxskill`).

## Calibration: Defaults That Read as Generated

Each of these is legitimate when the brief asks for it. When the brief leaves the axis open, do not spend that freedom here:

- Warm cream background with a high-contrast serif and one clay or terracotta accent.
- Near-black background with one acid-green or vermilion accent.
- Identical rounded cards, one radius everywhere, the same soft grey shadow, gradient washes as decoration.
- A tracked-out all-caps eyebrow over every heading, `A · B · C` meta strings, a spaced dash inside labels, an arrow appended to every link.
- Numbered markers (01, 02, 03) on content that is not a sequence.
- Fade-and-slide-up on every section and hover lift on every card.

## Worthwhile Style Directions

- Editorial / magazine
- Neo-brutalism
- Glassmorphism with real depth
- Dark luxury or light luxury with disciplined contrast
- Bento layouts
- Scrollytelling
- 3D integration
- Swiss / International
- Retro-futurism

Do not default to dark mode automatically. Choose the visual direction the product actually wants.

## Component Checklist

- [ ] Does it avoid looking like a default Tailwind or shadcn template?
- [ ] Does it have intentional hover/focus/active states?
- [ ] Does it use hierarchy rather than uniform emphasis?
- [ ] Would this look believable in a real product screenshot?
- [ ] If it supports both themes, do both light and dark feel intentional?
- [ ] Does it hold up in RTL as well as LTR, with type chosen for every script it renders?
- [ ] Is the one memorable element obvious, and is everything around it quiet?
