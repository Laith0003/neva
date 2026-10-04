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
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. RTL-first and Blade sections added from Neva house practice. -->
> This file extends [common/coding-style.md](../common/coding-style.md) with web-specific frontend content.

# Web Coding Style

## File Organization

Organize by feature or surface area, not by file type:

```text
src/
├── components/
│   ├── hero/
│   │   ├── Hero.tsx
│   │   ├── HeroVisual.tsx
│   │   └── hero.css
│   ├── scrolly-section/
│   │   ├── ScrollySection.tsx
│   │   ├── StickyVisual.tsx
│   │   └── scrolly.css
│   └── ui/
│       ├── Button.tsx
│       ├── SurfaceCard.tsx
│       └── AnimatedText.tsx
├── hooks/
│   ├── useReducedMotion.ts
│   └── useScrollProgress.ts
├── lib/
│   ├── animation.ts
│   └── color.ts
└── styles/
    ├── tokens.css
    ├── typography.css
    └── global.css
```

## CSS Custom Properties

Define design tokens as variables. Do not hardcode palette, typography, or spacing repeatedly:

```css
:root {
  --color-surface: oklch(98% 0 0);
  --color-text: oklch(18% 0 0);
  --color-accent: oklch(68% 0.21 250);

  --text-base: clamp(1rem, 0.92rem + 0.4vw, 1.125rem);
  --text-hero: clamp(3rem, 1rem + 7vw, 8rem);

  --space-section: clamp(4rem, 3rem + 5vw, 10rem);

  --duration-fast: 150ms;
  --duration-normal: 300ms;
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
}
```

## Animation-Only Properties

Prefer compositor-friendly motion:
- `transform`
- `opacity`
- `clip-path`
- `filter` (sparingly)

Avoid animating layout-bound properties:
- `width`
- `height`
- `top`
- `left`
- `margin`
- `padding`
- `border`
- `font-size`

## Semantic HTML First

```html
<header>
  <nav aria-label="Main navigation">...</nav>
</header>
<main>
  <section aria-labelledby="hero-heading">
    <h1 id="hero-heading">...</h1>
  </section>
</main>
<footer>...</footer>
```

Do not reach for generic wrapper `div` stacks when a semantic element exists.

## Naming

- Components: PascalCase (`ScrollySection`, `SurfaceCard`)
- Hooks: `use` prefix (`useReducedMotion`)
- CSS classes: kebab-case or utility classes
- Animation timelines: camelCase with intent (`heroRevealTl`)

## RTL-First Layout (bidirectional by default)

Every surface ships working in both directions or it does not ship. Build the layout once with logical properties and let `dir` flip it.

- Set `lang` and `dir` on `<html>` from the active locale (`<html lang="ar" dir="rtl">`). Never infer direction from the browser.
- Use logical properties, never physical ones, for anything that should mirror:
  - CSS: `margin-inline-start`, `padding-inline-end`, `inset-inline-start`, `border-inline-start`, `text-align: start`.
  - Tailwind: `ms-*` `me-*` `ps-*` `pe-*` `start-*` `end-*` `text-start` `text-end` `rounded-s-*` `rounded-e-*` `border-s` `border-e`. Treat `ml-*`, `mr-*`, `pl-*`, `pr-*`, `left-*`, `right-*`, `text-left`, `text-right` as lint findings unless the element must not mirror.
- Flex and grid follow `dir` automatically. Do not add `flex-row-reverse` to fake RTL.
- Mirror directional icons (chevrons, back and forward arrows, progress) with `rtl:-scale-x-100` or `[dir=rtl] & { transform: scaleX(-1) }`. Do not mirror logos, media controls that match physical devices, clocks, or checkmarks.
- Directional motion follows reading direction: a panel that enters from the start edge enters from the right in RTL. Derive offsets from `dir`, do not hardcode `x: -100`.
- Numbers, phone numbers, codes, URLs, and emails inside RTL text are LTR islands: wrap them in `<bdi>` or `<span dir="ltr">` so punctuation does not jump.
- Pick one digit system per product (Arabic-Indic or Latin) and format with `Intl.NumberFormat(locale, { numberingSystem })`; never mix both on one screen.
- Choose fonts with real Arabic (or other script) coverage and matching weights; do not let the browser fall back per glyph. Arabic needs more line-height than Latin; never apply letter-spacing to Arabic, it breaks the joins.
- Test every screen in both directions before calling it done (see [testing.md](testing.md)).

## Blade, Alpine, and Tailwind

- Blade components (`<x-...>`) are the canonical surface for repeated UI. Extend an existing component rather than forking its markup.
- Echo with `{{ }}`. `{!! !!}` only for HTML you sanitized yourself, with a comment saying where.
- Keep Alpine state small and local (`x-data` per component). Move anything longer than a few lines into a named `Alpine.data('name', () => ({ ... }))` registration instead of inline objects.
- Do not introduce a SPA framework into a Blade app to solve one widget; reach for Alpine first, then a server-rendered partial.
- Every user-facing string goes through `__()` or `@lang` with keys present in every locale file in the same change.
