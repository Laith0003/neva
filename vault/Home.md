---
tags: [map]
status: active
---

# Home

Start here. This vault is your agent's memory and your record of your world, in plain
markdown you own, edit, and can read without it.

- [[CLAUDE]] is the operations manual: folder map, the one-person-one-note rule, money rules
- [[GOALS]] holds what you are working toward
- [[Dashboard]] is the single-pane view of what's active and what moved recently
- 08 Journal collects daily notes; 09 Reviews collects the weekly rhythm
- Your agent keeps its observations in 06 Memory and asks before touching canon

If you write in Arabic, or any right-to-left language, see
[[RTL and Arabic notes]] before your first note: one frontmatter property, set once.

## What's moving

```base
filters:
  and:
    - file.mtime > now() - "7d"
    - file.name != "README"
    - file.name != "CLAUDE"
    - file.name != "Home"
    - file.name != "Dashboard"
    - "!file.inFolder(\"Templates\")"
    - "!file.inFolder(\"Skills\")"
    - "!file.inFolder(\".obsidian\")"
views:
  - type: table
    name: This week
    limit: 10
    order:
      - file.name
      - file.folder
      - file.mtime
```

A short table on a new vault is correct, not broken: there is not much to show yet. Ask your
agent to do something, and this fills in on its own. Every folder in the vault explains
itself the first time you open it; look for a short note at the top of an empty one.

[[Dashboard]] goes deeper once there's more here: active projects, clients, people, the inbox.
