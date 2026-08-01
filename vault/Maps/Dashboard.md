---
tags: [map]
date: {{date}}
status: active
---

# Dashboard

Single pane on the vault: what's active, what moved recently, what's waiting in the inbox.
Built with Bases, the view engine that ships inside Obsidian itself (1.9 and later, on by
default in this vault). Nothing below needs a plugin install or the "turn on community
plugins" prompt. If a table looks blank on a fresh vault, that's correct: there is nothing to
show yet, not a broken query. It fills in as you use the vault.

## Active projects

```base
filters:
  and:
    - file.inFolder("01 Projects")
    - file.name != "README"
views:
  - type: table
    name: Projects
    order:
      - file.name
      - status
      - deadline
      - file.mtime
```

## Active clients

```base
filters:
  and:
    - file.inFolder("02 Clients")
    - file.name != "README"
views:
  - type: table
    name: Clients
    order:
      - file.name
      - status
      - file.mtime
```

## People

```base
filters:
  and:
    - file.inFolder("03 People")
    - file.name != "README"
views:
  - type: table
    name: People
    order:
      - file.name
      - status
```

Full history and disambiguation notes, if you keep them, belong in prose in 03 People itself;
a table is for finding someone fast, not for the story of the relationship.

## Moved in the last two weeks

```base
filters:
  and:
    - file.mtime > now() - "14d"
    - file.name != "README"
    - file.name != "CLAUDE"
    - file.name != "Home"
    - file.name != "Dashboard"
    - "!file.inFolder(\"Templates\")"
    - "!file.inFolder(\"Skills\")"
    - "!file.inFolder(\"Maps\")"
    - "!file.inFolder(\".obsidian\")"
views:
  - type: table
    name: Recent
    limit: 20
    order:
      - file.name
      - file.folder
      - file.mtime
```

## Inbox

```base
filters:
  and:
    - file.inFolder("00 Inbox")
    - file.name != "README"
views:
  - type: list
    name: Inbox
```

Say "check the inbox" and your agent files each item and clears this list.

---

[[Home]], [[GOALS]], [[CLAUDE]]
