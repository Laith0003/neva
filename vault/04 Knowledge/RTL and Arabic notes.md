---
tags: [reference]
date: {{date}}
status: active
---

# RTL and Arabic notes

This vault mixes English and Arabic. Obsidian's built-in reading-direction toggle guesses
direction per line from the first word, and gets it wrong on mixed content: a note with a
name or number at the start of an Arabic line flips back to left-to-right and the rest reads
in the wrong order. Do not rely on it for a whole note.

## The fix that holds

Add one property to a note's frontmatter:

```
cssclasses: [rtl]
```

That's it. The whole note (editor and reading view) becomes right-to-left, in one property,
and it survives re-opening the note, re-launching Obsidian, and syncing to another device,
because it lives in the note itself, not in app state. The `.obsidian/snippets/rtl.css`
snippet that ships with this vault is what reads that class; it is enabled by default in
Settings > Appearance > CSS snippets, and it never touches notes that do not set the class.

Code blocks, inline code, and links inside an RTL note stay left-to-right on purpose. Phone
numbers and dates read correctly either way.

## What this deliberately does not do

No RTL plugin is bundled. The community RTL plugins are small, single-maintainer projects; a
frontmatter property plus a CSS snippet is zero-dependency and does not need to keep working
against an Obsidian API it does not use. If you outgrow this (per-paragraph mixed direction
inside one note, for example), a plugin is a reasonable next step, not a requirement to start.

## Person notes and phone numbers

Templates/Person.md is language-neutral by design; write the "Facts" and "Relationship"
sections in whichever language you actually think in, and add `cssclasses: [rtl]` if that
language is Arabic. Phone numbers stay left-to-right automatically since the snippet only
flips text and table direction, not digit order.
