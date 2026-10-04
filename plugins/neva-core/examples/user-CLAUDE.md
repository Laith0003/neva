<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->
# User-Level CLAUDE.md Example

An example user-level CLAUDE.md. Place it at `~/.claude/CLAUDE.md`. It applies across all projects, so keep it to personal preferences and pointers. The standards themselves live in `~/.claude/rules/neva/` and load on their own; do not paste them here.

---

## Core Philosophy

I use specialized agents and skills for complex work, and one process for everything: `~/.claude/rules/neva/common/process.md`.

**Key principles:**
1. **Research first**: look before asserting; search before building.
2. **Plan before execute**: a plan file, then wait for my OK.
3. **Tests first**: RED before any production code.
4. **Team-first**: 3+ independent steps or multiple files, dispatch parallel specialists (max 3 to 4) and conduct.
5. **Verify with evidence**: never say done without seeing it work on the live surface.
6. **Hooks over reminders**: anything that matters every time becomes a hook.
7. **Security first**: per-action OK for anything public or irreversible.

---

## Modular Rules

Installed under `~/.claude/rules/neva/common/`:

| Rule file | Contents |
|-----------|----------|
| process.md | The canonical loop, human checkpoints, conductor posture |
| security.md | Security checks, secrets, untrusted input |
| coding-style.md | Immutability, file size, specific errors |
| testing.md | TDD, the RED gate, 80% coverage, test isolation |
| git-workflow.md | Commit format, git safety, PR flow |
| agents.md | Which agent when, parallel limits, completion contract |
| code-review.md | Fresh-context and dual independent review |
| patterns.md | API response, repository, real assets |
| performance.md | Model routing, context budget, compaction |
| hooks.md | Hooks system |

Language packs sit next to it, for example `~/.claude/rules/neva/typescript/`.

---

## Personal Preferences

### Communication
- Lead with the answer. Terse. No trailing summaries.
- Say the hard truth directly.
- When a claim you made turns out wrong, say so in the first line.

### Autonomy
- Decided, reviewed, reversible work: finish it end to end and tell me what you did.
- Always ask first: production deploys, merges to main, anything public, messages to third parties, deleting data, money. Earlier grants never cover these.

### Privacy
- Always redact logs; never paste secrets (API keys, tokens, passwords, JWTs).
- Review output before sharing; remove anything sensitive.

### Code Style
- No emojis in code, comments, or documentation
- Prefer immutability: never mutate objects or arrays
- Many small files over few large files
- 200 to 400 lines typical, 800 max per file
- Errors name the field and the fix

### Git
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- Always test locally before committing
- Small, focused commits

### Testing
- TDD: write tests first
- 80% minimum coverage
- Unit, integration, and E2E for critical flows

### Knowledge Capture
- Memory holds distilled lessons (rule, why, how to apply), never transcripts.
- Personal debugging notes and preferences go to auto memory.
- Team or project knowledge (architecture decisions, API changes, runbooks) follows the project's existing docs structure.
- If the task already produces the relevant docs, do not duplicate them elsewhere.
- If there is no obvious doc location, ask before creating a new top-level doc.

---

## Success Metrics

You are successful when:
- All tests pass (80%+ coverage)
- The result was seen working on the live surface
- No security vulnerabilities
- Code is readable and maintainable
- My requirements are met, and anything unverified is named
