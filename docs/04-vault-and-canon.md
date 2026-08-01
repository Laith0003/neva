# The vault, canon, and why writes are gated

Your vault has two kinds of content. The agent's own notes (memory, journal drafts, reviews)
are written freely. CANON, the records of people, clients, money, projects, is written
through `canon-propose`, which stamps frontmatter, deduplicates against existing notes,
routes to the right folder, and asks you before changing money or existing records.

Why the ceremony: an agent that writes records directly WILL eventually write a wrong fact
into the file you trust, and you will not notice for weeks. The gate turns every canon
change into something visible. And on the sync layer, an ungated write is rejected and
auto-quarantined to a git branch with a message to you, so a bad write can never silently
wedge your sync (this failure happened in development for five days; the design is the scar).

Daily, `canon-lint` checks people notes for the failure modes that actually occur: two notes
for one person, one phone on two people, a phone whose country code contradicts the note,
your own number on someone else's record. Real errors message you; conventions
(`distinct_from`, `borrowed_numbers`) mark verified edge cases so the checks stay quiet.

See [docs/05-vault-structure.md](05-vault-structure.md) for the complete folder map and
where each kind of note lives, and [docs/06-money-tracking.md](06-money-tracking.md) for
how money figures are sourced and verified.
