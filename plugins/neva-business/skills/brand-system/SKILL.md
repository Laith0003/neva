---
name: brand-system
description: Use when defining or onboarding a brand, writing brand guidelines, or when output does not feel on-brand. Encodes the brand as one owner-approved document that every design, content and image task loads first and treats violations of as bugs.
---
<!-- Generalized for Neva from a local skill; no ECC source. -->

# Brand System

One brand document per brand. It is the north star: if an output does not fit it, the output does not ship.

## Operating Rule for Every Other Skill

At the start of any design, content or image task for a brand, load its brand document (for example `docs/brand-direction.md` in the brand's repo, or wherever the user keeps it). Treat violations as bugs: wrong font, off-voice copy, an image that breaks the imagery rules. Flag and fix; do not ship and mention.

If no brand document exists, run this skill first. If the brand has a finished `brand-discovery` brandbook, build the document from it instead of re-interviewing.

## Building the Document

Interview the owner, then fill the template. Push for specifics: "modern and clean" is not an answer. Ask for reference brands and exactly what to take from each, and one brand they never want to resemble.

```
# <Brand> - Brand Direction

The north star for every design, image and copy decision. If something does not fit this, it does not ship.

## Soul
- Positioning in one or two lines. What energy, which reference brands, what it is NOT.
- Cultural grounding: language-first stance, values, what stays tasteful versus cliche.

## Imagery (non-negotiable)
- What every hero and product page must include (people, flat-lay, editorial sets).
- Hard bans (mannequins, distorted anatomy, color bleed, stock-photo look, whatever the brand rejects).
- Required shot set per product.

## Type
- Heading face and logo treatment. Body and UI face. Available weights.

## Color
- The palette, what carries color (often the photography), and explicit exclusions.

## Layout and feel
- Alignment, density, signature moves, mobile-first, RTL if applicable.

## Voice
- Register and language per surface. Forbidden vocabulary and punctuation. Required phrases and spellings.
```

Keep it under a page. A brand document nobody rereads is decoration. Detailed voice work belongs in the `brand-voice` profile, which refines this Voice section and must not contradict it.

## Example (synthetic)

```
# Northline Socks - Brand Direction

## Soul
- Editorial but calm. Reference energy: a fashion campaign, never a discount store. Not generic dropshipping.
- Arabic-first, rooted in local identity without cliche.

## Imagery
- Heroes and product pages always include people. Worn-on-foot, one lifestyle shot, one detail, clean product shots.
- Bans: mannequins, plastic skin, color bleed.

## Type
- Headings and logo: a bold serif display. Body, UI, prices and numerals: the matching sans.

## Color
- Black and white. Photography carries color. No green accents.

## Layout and feel
- Centered homepage. Product photos fade into the page instead of sitting in hard boxes. Mobile-first, RTL correct.

## Voice
- Terse, confident, specific. No emojis, no em-dashes, no "world-class", no exclamation marks.
```

## Safety

- The document is owner-approved before use: show the draft, get an explicit yes, then save.
- Never silently edit an existing brand document; propose changes as a diff.
- When a task conflicts with the document, stop and surface the conflict instead of picking a side.
