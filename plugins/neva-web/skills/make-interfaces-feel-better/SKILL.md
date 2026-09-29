---
name: make-interfaces-feel-better
description: Apply concrete design-engineering details that make interfaces feel polished. Use when reviewing or improving UI spacing, typography, borders, shadows, motion, hit areas, icons, text wrapping, and interaction states.
metadata:
  origin: affaan-m/ECC (MIT), adapted for Neva
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. States, layout alignment, and content checks informed by the open taste-skill redesign audit; bidirectional details from Neva house practice. -->

# Make Interfaces Feel Better

Use this skill for the small design-engineering details that compound into a
more polished interface.

Source: salvaged from stale community PR #1659 by `linus707`.

## When to Use

- The user says the UI feels off, flat, generic, cramped, jumpy, or unfinished.
- You are building controls, cards, lists, dashboards, navigation, forms, or
  toolbars.
- A component needs hover, active, focus, enter, exit, loading, or empty states.
- A frontend review needs specific before/after recommendations.

## Core Principles

### Concentric Radius

For nearby nested rounded surfaces:

```text
outer radius = inner radius + padding
```

If padding is large, treat layers as separate surfaces instead of forcing the
math. The point is optical coherence, not formula worship.

### Optical Alignment

Geometric centering is not always visual centering. Icon buttons, play
triangles, arrows, stars, and asymmetric icons often need a small offset. Fix the
SVG when possible; otherwise adjust with a pixel-level margin or padding change.

### Shadows And Borders

Use borders for separation and focus rings. Use layered shadows when a card,
button, dropdown, or popover needs depth. Shadows should be transparent and
subtle enough to work across backgrounds.

### Text Wrapping

- Use `text-wrap: balance` on headings and short titles.
- Use `text-wrap: pretty` on short-to-medium body text, captions, descriptions,
  and list items.
- Avoid both on long prose, code, and preformatted content.
- Use `font-variant-numeric: tabular-nums` for counters, timers, prices, tables,
  and other updating numbers.

### Font Smoothing

On macOS, apply antialiased font smoothing at the root layout when the project
does not already do so:

```css
html {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

### Image Outlines

Images often need a subtle inset outline so their edges do not blur into the
surface.

```css
img {
  outline: 1px solid rgba(0, 0, 0, 0.1);
  outline-offset: -1px;
}

@media (prefers-color-scheme: dark) {
  img {
    outline-color: rgba(255, 255, 255, 0.1);
  }
}
```

Use neutral black or white alpha outlines. Do not tint image outlines with the
brand palette.

### Motion

Use CSS transitions for interactive state changes because they can retarget
when the user changes intent mid-motion. Reserve keyframes for staged
one-shot entrances or loading sequences.

Good motion defaults:

- Enter: combine opacity, small `translateY`, and optionally blur.
- Exit: shorter and quieter than enter, usually 150ms.
- Press: `scale(0.96)` for tactile buttons, with a way to disable it when the
  movement distracts.
- Icon swaps: cross-fade with opacity, scale, and blur instead of instant
  visibility toggles.

### Transition Scope

Never use `transition: all`. Specify the changed properties:

```css
.button {
  transition-property: transform, background-color, box-shadow;
  transition-duration: 150ms;
  transition-timing-function: ease-out;
}
```

Use `will-change` only for first-frame stutter on compositor-friendly
properties such as `transform`, `opacity`, and `filter`. Never use
`will-change: all`.

### Aligned Rhythm Across Siblings

- Side-by-side cards, pricing columns, and panels align shared elements (title, price, feature list, button) on the same baseline. Pin buttons to the bottom of each card.
- Vary radius by level: tighter inside, softer on containers. One radius everywhere reads as a template.
- Bottom padding often needs to be slightly larger than top to look equal.
- Full-height sections use `min-height: 100dvh`, never `height: 100vh` (mobile toolbars jump).
- One shadow light source across the page; tint shadows toward the surface hue instead of pure black.

### Every State Exists

Hover, focus-visible, active or pressed, disabled, loading (skeletons shaped like the content, not a lone spinner), empty (an invitation to act), and error (inline, specific: name the field and the fix). No `window.alert()`, no links to `#`, and the current page is marked in navigation.

### Bidirectional Polish

- Spacing and alignment use logical properties so RTL mirrors for free.
- Directional icons (chevrons, back, forward, progress arrows) mirror in RTL; logos, checkmarks, and media transport controls do not.
- Enter motion follows reading direction.
- Phone numbers, prices, and codes inside RTL text sit in `<bdi>` or `dir="ltr"` islands.
- Never letter-space Arabic; give it more line-height than Latin.

### Content That Does Not Look Generated

No lorem ipsum, no "Jane Doe", no round fake metrics, no filler verbs ("elevate", "seamless", "unleash"). Sentence case headings. Errors state what happened and how to fix it; success messages without exclamation marks.

### Hit Areas

Interactive controls should have at least a 40x40px hit area, ideally 44x44px
where the layout allows it. Expand with a pseudo-element when the visible icon
is smaller, but do not let expanded hit areas overlap.

## Review Output

When reviewing a UI polish pass, report concrete changes in before/after rows:

| Principle | Before | After |
| --- | --- | --- |
| Concentric radius | Same radius on parent and child | Parent radius accounts for padding |
| Tabular numbers | Counter shifts as digits change | Counter uses `tabular-nums` |
| Transition scope | `transition: all` | Explicit transition properties |

Include file paths and properties when they are not obvious from the snippets.
Omit principles that you checked but did not change.

## Checklist

- Nested rounded elements are optically coherent.
- Icons are visually centered.
- Buttons, cards, and popovers use borders or shadows for the right reason.
- Headings and short text avoid awkward wrapping.
- Dynamic numbers use tabular numerals.
- Images have neutral outlines where needed.
- Enter and exit animations are split, subtle, and interruptible where
  appropriate.
- Buttons have tactile active states without exaggerated motion.
- `transition: all` and `will-change: all` are absent.
- Small controls still have usable hit areas.
- Sibling cards and columns align titles, lists, and buttons.
- Hover, focus, active, disabled, loading, empty, and error states all exist.
- RTL mirrors correctly and LTR islands hold their order.
- The pass was verified on a rendered screenshot, not only in code.
