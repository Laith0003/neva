---
tags: [memory, instincts]
---

# Instincts

Small lessons your agent learned from watching its own sessions: one trigger, one action, a
confidence score, and the evidence behind it. One note per instinct, readable and editable here.

| Folder | What is in it |
|---|---|
| project/<project-id>/ | lessons from one codebase or folder; only that project loads them |
| global/ | lessons that hold everywhere; only you promote an instinct here |
| pending/ (inside either) | imported instincts waiting for review; deleted after 30 days |

How they get here: a hook records each tool call on this machine (never in this vault), and a
nightly job reads those records and writes or updates project instincts. Anything bigger (a
global instinct, a skill, a command, a rule) is only ever proposed, in an "Instinct promotions"
note in the inbox folder, and written after you tick approve.

Strong instincts (confidence 0.7 or more) are shown to your agent at the start of each session.
To retire one, set `status: archived` in its note; to change one, edit its Action line.
