# Changelog

## neva-core 0.11.0, neva-library 0.11.0 (2026-10-29) - the core split

`neva-core` loaded 94 skills, 54 commands and 30 agents into every session, about 12,600
tokens of names and descriptions, and almost none were used. It now keeps what the loop needs
and the rest moves to a new opt-in plugin. The set of items is unchanged; only their paths and
`neva-library:` references were updated.

Claude Code gets a slim always-on core with an opt-in library. The adapters for every other
harness (Codex, OpenCode, Gemini, Cursor, Copilot, Kiro and the rest) keep the same items:
they project core plus library, the same 94 skills, 54 commands and 30 agents as 0.10.x,
because those harnesses cannot enable a plugin per project.

### Changed
- `neva-core` keeps 9 skills (search-first, iterative-retrieval, tdd-workflow,
  verification-loop, browser-qa, safety-guard, strategic-compact, continuous-learning-v2,
  neva-guide), 13 commands (plan, code-review, learn, evolve, promote, projects, prune,
  instinct-status, instinct-export, instinct-import, epic-sync, epic-validate, epic-review),
  2 agents (code-reviewer, security-reviewer), and every hook, rule, context, script and
  workflow. Always-on cost: about 1,450 tokens (`claude plugin details`).
- Core and the six domain plugins (now 0.11.0) name library items as `neva-library:<name>`, say the
  library is opt-in, and give the core fallback.
- The adapters project core plus library (`ADAPTER_PLUGINS` in `build/adapters.py`). Codex also
  enables `neva-library@neva`.
- Library files reach their own files through `scripts/neva_core.py library <path>`, so the same
  text works whether `CLAUDE_PLUGIN_ROOT` names the library (Claude Code) or `plugins/neva-core`
  (Codex and the adapters).

### Added
- `neva-library`: 85 skills, 41 commands and 28 agents, moved with `git mv`. Install it
  disabled and enable it per project in `.claude/settings.json` `enabledPlugins`.
- `scripts/neva_core.py`, byte-identical in both plugins: finds the other plugin (override
  variable, sibling checkout, or plugin cache), prints a path in it, or runs a core script.
- `build/check-plugin-refs.py` and `build/verify.sh` section 30: fail on a dangling
  `plugin:name`, a non-library plugin that uses a library-only item by a bare name, or a
  `${CLAUDE_PLUGIN_ROOT}` path missing from its plugin, with planted negative controls.

## 0.10.0 (2026-10-04) - the coding harness

Neva becomes two things in one repo: the honest second brain, and a disciplined coding harness
for Claude Code, shipped as a plugin marketplace with eight plugins.

### Added
- `neva-core`: one canonical process loop (`rules/process.md`), merged planner, architect,
  code reviewer, security reviewer and TDD guide, 60 commands, and about 110 skills covering
  research-first, verification, compaction, orchestration and learning.
- A Python standard-library hook runtime: one dispatcher per event, profiles
  `minimal|standard|strict`, per-module switches, crash isolation. It blocks `--no-verify`,
  protects lint and format configs, nudges compaction from real token counts, trips a circuit
  breaker on failing MCP servers, writes session summaries and a pre-compact note, and logs
  cost. Transcript parsing is incremental, so a long session costs milliseconds per response.
- Instincts: tool use is observed, a nightly job distils lessons into markdown notes in the
  vault, and promotion to durable memory waits for your approval in the inbox.
- Seven domain plugins (web, mobile, backend languages, ops, business, media, domains), meant to
  be enabled per project.
- `build/verify.sh` section 25: the marketplace, hook registration, both test suites, plugin
  validation, and a negative control proving one broken module cannot break a session.
- CI on macOS and Linux (leak scan, licence guard, acceptance harness) plus gitleaks.

### Credit
Much of the harness is adapted from Everything Claude Code by Affaan Mustafa (MIT). Sponsor,
paid-service and account-bound pieces were dropped; every outbound action stops for a human yes.

## 0.9.0 (2026-08-01) - first public release

Not 1.0, and the reason is specific: the macOS path is proven and the Linux path has never
been executed. Everything else is ready.

### Proven
- 38-check acceptance harness. It installs from scratch in a fresh HOME with a deliberately
  stripped PATH, then asserts outcomes a user would notice rather than exit codes. Every
  check has been proven able to fail by breaking the thing it watches.
- Covered: second installs over an existing one, non-ASCII notes and queries, vault paths
  containing spaces, grounded search with ripgrep absent, BSD and GNU divergence, the
  approval queue in both directions, and doctor's exit code against a broken install.

### Fixed before release, each found by someone pretending to be a buyer
- The leak scanner did not scan itself, so a real identifier could sit in `build/` forever.
  It also stored real secrets as literal strings, which is a disclosure the moment a repo is
  public. The denylist now lives outside the repository and the tool announces when it is
  inactive rather than printing "clean" while checking nothing.
- `doctor` could print a CRITICAL failure and return success.
- The installer enabled a background job on install day and the documented way to remove it
  did not work.
- The two documented fixes for the one failure every new install shows were both broken,
  which left a new user in a loop four steps into the README.
- The installer could write into an existing agent workspace without consent.
- A notification tool logged "sent" without checking whether the send succeeded.
- Money was described as coming only from the ledger while the code also read a cached block
  that nothing ever wrote.
- A feature was documented as shipped that no code implemented.

### Known and stated rather than hidden
- Linux: never run end to end. The systemd units have never been loaded.
- Spoken voice does not exist. The word "voice" in these docs means writing style.
- The setup interview has been run by two independent testers and by nobody else.
