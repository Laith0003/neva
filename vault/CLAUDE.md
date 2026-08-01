# Vault operations manual

This vault is the memory of your assistant and the record of your world. The agent reads it
before answering anything factual and writes to it as you work together. You own every file;
open anything in Obsidian, edit anything, delete anything.

## The one rule that makes everything work

**Facts live in notes, and the agent only asserts what a note contains.** If you ever catch
it stating something about your world that is not in a note, that is a bug in its behavior,
not a feature. Tell it; it will show you the source or retract.

## Folder map

| Folder | What lives there | Who writes |
|---|---|---|
| 00 Inbox | quick captures, unsorted | you, and the agent when unsure |
| 01 Projects | one note per active project | both, gated |
| 02 Clients | one note per client or engagement | both, gated |
| 03 People | ONE note per person, never two | both, gated |
| 04 Knowledge | reference material, methods | both, gated |
| 05 Money | the hledger journal + money notes | gated, ledger is the only source of figures |
| 06 Memory | the agent's distillations and observations | agent |
| 07 Archive | finished things | both |
| 08 Journal | daily notes | you, agent drafts if asked |
| 09 Reviews | weekly, quarterly, yearly reviews | agent drafts, you edit |
| 10 Personal | private life notes | you |
| Food | markdown food log, one file per month | both |
| Maps | index notes tying areas together | agent |
| Templates | note templates | ships with the vault |
| Skills | agent skills you can invoke by name | ships, extend freely |

## People notes

One person, one note. Nicknames in frontmatter, never separate files:

```yaml
---
tags: [person]
aliases: [Abu Omar]
distinct_from: []        # verified different people who look related
borrowed_numbers: []     # numbers listed here that belong to someone else
---
```

## Money

Figures come from `05 Money/<year>.journal` (hledger plain-text accounting) and nowhere
else. The agent appends transactions and reports with `hledger` commands; if a figure is not
in the journal, the agent says it does not know it. This is deliberate and is the reason its
money answers can be trusted.

## Reviews cadence

The agent watches staleness and offers to draft: weekly review after 7 days, journal nudge
after 4, long-term plan check after 30. It drafts, you edit. Skipping is always allowed;
the point is that forgetting is impossible.
