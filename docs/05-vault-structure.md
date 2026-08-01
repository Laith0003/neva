# Vault structure: where facts live

Your vault is a folder of plain markdown files organized by type. The agent searches only
folders marked LIVE (current facts, not archive) and refuses to answer from archived or
historical content. One person one note, enforced by canon-lint daily.

## Folder reference

| Folder | Purpose | Canonical? | Who writes |
|---|---|---|---|
| 00 Inbox | Quick captures, unsorted, temporary | No | You and agent |
| 01 Projects | One note per active project | Yes | Both, gated |
| 02 Clients | One note per client or engagement | Yes | Both, gated |
| 03 People | ONE note per person, never two | Yes | Both, gated |
| 04 Knowledge | Reference material, methods, how-tos | Yes | Both, gated |
| 05 Money | hledger journal + money notes | Yes | Both, gated |
| 06 Memory | Agent's distillations and observations | No | Agent only |
| 07 Archive | Finished projects, old notes | No | Both |
| 08 Journal | Daily notes, log entries | No | You; agent drafts if asked |
| 09 Reviews | Weekly, monthly, yearly reviews | No | Agent drafts; you edit |
| 10 Personal | Private life notes | No | You only |
| Food | Markdown food log, one file per month | No | Both |
| Maps | Index notes tying areas/topics together | No | Agent and you |
| Templates | Note templates shipped with vault | No | Ignore |
| Skills | Agent skills you can invoke by name | No | Ignore (extend in your workspace) |

## How the agent finds things

When you ask a question, the agent:
1. Searches LIVE folders (01, 02, 03, 04, 05) for matching notes
2. Reads those notes and answers only from what they contain
3. Names the source file so you can open it and verify
4. Says "I don't have that" if no note matches

The agent will not:
- Make up an answer if a note doesn't exist
- Search in 06 Memory or 07 Archive (historical, not current truth)
- Read from Inbox without confirming

## Where to put things

**Project notes (01 Projects):**
- One note per project; title is the project name
- Include: goal, deadline if any, people involved, current status
- Agent uses this to ask context-aware progress questions
- Example: "Redesign Dot" or "Neva OS paid tier"

**Client notes (02 Clients):**
- One note per client or engagement; title is the client name
- Include: contact, rate/contract, active projects, outstanding balances
- Canon-propose enforces no duplicate clients
- Example: "Northwind Retail" or "Company Inc"

**People notes (03 People):**
- ONE note per person, never two for the same person
- Include: role, phone, email, nicknames, where you see them
- Canon-lint enforces this daily and alerts you on duplicates
- Nicknames (optional): use YAML frontmatter: `nicknames: [Abu Omar]`
- If two people share a number: mark one as `borrowed_numbers: [<number>]`
- Example: "Alice (client)" or "Bob (colleague)"

**Money notes (05 Money):**
- The hledger journal (2026.journal, etc.) is the source of all figures
- One transaction per entry, never edited after written; the agent appends new transactions
- Optional: supporting notes explaining invoices, contracts, or money decisions
- The agent reports figures with `hledger` commands; if a figure is not in the journal, it says so
- Example: "Invoice 001" or "Quarterly budget"

**Knowledge (04 Knowledge):**
- How-tos, methods, recipes, research summaries
- Agent reads these to understand context (e.g., "our process for shipping a release")
- Not canonical (facts you assert go in People/Projects/Money, not here)
- Example: "How to write a spec" or "Meeting notes from Y"

## Gated writes: canon-propose

When you use canon-propose to add or edit notes in 01-05 folders, it:
1. Checks frontmatter (type, timestamp)
2. Deduplicates against existing notes
3. Routes to the right folder
4. For Money or edits to existing records: waits for your approval before writing

Example: `canon-propose people "Alice Jones" --mode new` opens an editor, then asks your
approval before writing to 03 People/Alice Jones.md.

If the agent writes to 01-05 directly without canon-propose, the write is rejected and
quarantined to a git branch with a message to you. This failure happened in development; the
gate is the scar that prevents it.

## Daily checks: canon-lint

Every morning, canon-lint runs and checks:
- Two notes for one person (duplicate people)
- One phone number on two people (duplicated contact)
- A phone whose country code contradicts the note (e.g., +31 for Netherlands but note says
  Saudi)
- Your own number on someone else's record (security check)

If it finds real errors, it messages you. If you have verified edge cases (two people who
share a number, or someone with documented "distinct_from" relationships), mark them in
frontmatter and canon-lint stays quiet.

---

See [docs/04-vault-and-canon.md](04-vault-and-canon.md) for how the agent grounds answers in
these files.
