# The neva CLI: installing into a coding harness

`bin/neva` is the one entry point for putting Neva into a coding harness and for taking it back
out. Python standard library only, no dependencies, no network.

```
neva install --harness claude --plugins core,web --profile standard --yes
neva doctor
neva repair
neva uninstall
neva list
```

Run `neva <command> --help` for the flags. `install.sh` calls `neva install` for you at step 6;
answer `none` to that question, or set `NEVA_HARNESS=none`, to be given the commands instead.

The `neva` on your PATH is `~/.local/bin/neva`, a link into `~/.local/neva`. `install.sh` copies
everything it reads into that prefix (the plugins with their rules and hooks, the marketplace
manifest, any adapters), and the marketplace is registered from there, so the CLI and the
plugins keep working after the checkout you installed from is moved or deleted.

## What install writes

**Claude Code** is installed natively:

| What | Where |
|---|---|
| Rules, neva-core's | `~/.claude/rules/neva/common/` |
| Rules, each enabled plugin's language packs | `~/.claude/rules/neva/<lang>/` |
| `NEVA_HOOK_PROFILE`, `NEVA_PLUGINS`, `NEVA_CLAUDE_BIN` | the `env` object inside `~/.claude/settings.json` |
| The marketplace and the plugins | through the `claude plugin` CLI, recorded only when this install added them |

Only the keys in that table are touched inside `settings.json`. Every other key keeps its value,
and the file is backed up before the first write either way. If `settings.json` is a symlink into
a dotfiles repository, Neva writes through it to the file it points at and leaves the link in
place; uninstall puts that file's bytes back.

Writing into Claude Code's own settings and plugin registry is on by default, including a
hands-free `install.sh` or `upgrade.sh`. Before it writes, `neva install` prints each settings key
and value it will set and each `claude plugin` command it will run. To keep Claude Code's settings
and plugin registry untouched, pass `--no-claude-settings` (for `install.sh`, set
`NEVA_CLAUDE_SETTINGS=no`): only the rules are installed, and the keys and commands are printed for
you to apply by hand. `neva doctor` then reports the settings as skipped, not missing.

**Every other harness** comes from a data contract, so adding one is adding a directory rather
than changing code. That includes instruction-only targets that have no CLI of their own: give
them a `detect.paths` and a `copy` entry and they work like any other.

## The adapter contract

`adapters/<harness>/install.json`:

```json
{
  "harness": "codex",
  "detect": {"binaries": ["codex"], "paths": ["~/.codex"]},
  "entries": [
    {"src": "AGENTS.md", "dest": "~/.codex/AGENTS.md", "mode": "copy"},
    {"src": "prompt.md", "dest": "~/.codex/prompts/neva.md", "mode": "symlink"},
    {"src": "settings.json", "dest": "~/.codex/settings.json", "mode": "merge-json", "key": "neva.profile"},
    {"src": "config.toml", "dest": "~/.codex/config.toml", "mode": "merge-toml", "key": "tool.neva"},
    {"src": "block.sh", "dest": "~/.profile", "mode": "append-block", "key": "codex"}
  ],
  "post": ["codex auth login"]
}
```

| Field | Meaning |
|---|---|
| `detect` | How to tell this harness is on the machine. Any binary on PATH or any path that exists counts. |
| `src` | Relative to the adapter directory, then to the repo root. May be absolute. |
| `dest` | `~` and `${VAR}` expand. The result must be absolute and must not contain `..`, or the entry is refused before anything is written. |
| `mode` | `copy`, `symlink`, `merge-json`, `merge-toml`, `append-block`. |
| `key` | Dotted key for the merge modes, required: a merge entry without one is refused, because Neva never merges a whole file. For `append-block` it names the markers, `# neva begin <key>` and `# neva end <key>`. |
| `post` | Printed for you to run. Neva never runs them. |

The TOML support is deliberately small: tables, strings, integers, floats, booleans and flat
arrays. An array of tables, a multi-line string, a key set twice or a table declared twice (which
Python's `tomllib` refuses too) is refused by name rather than silently mangled. Keys may be bare,
"quoted" or 'literal', joined by dots; a quoted key keeps its dots and spaces when the file is
written back, and the tests check both directions against `tomllib`. When the table Neva adds
does not exist yet, Neva appends it at the end and leaves every existing byte, comments included,
in place; uninstall takes exactly those bytes out again. When it would have to rewrite the file
instead, it does so only if the file has no comments, and otherwise refuses with the key to set
by hand. Use `merge-json` where a harness offers both.

## The install-state manifest

`${NEVA_DATA_DIR:-~/.local/share/neva}/install-state.json` records every file, symlink, JSON key
and TOML key Neva wrote, and for each one:

- the harness that owns it,
- a checksum of exactly the part Neva owns, which is what `doctor` and `repair` compare against,
- the path of the timestamped backup of whatever was there first, under `.../backups/<stamp>/`,
- whether the destination existed at all before Neva first touched it,
- for a merged key, the value that key held before, so uninstall can hand it back,
- for a merged key, the containers Neva had to create, so uninstall can take them away again.

Nothing is overwritten without a backup first.

## What install, repair and uninstall refuse

Each refusal names the file and the fix, and leaves the file as it found it.

- A destination that resolves outside HOME at the moment of writing. This is checked again right
  before every backup, write, restore or delete, so a `~/.claude` symlinked out of HOME, or a
  managed file or directory swapped for an outside symlink after install, stops the command
  instead of steering it out. A symlink that stays inside HOME is fine; at a path Neva copies to,
  Neva replaces the link and never writes through it.
- A path Neva already owns whose layout changed since install, inside HOME or not. Each entry
  records the symlinks above it when Neva wrote it; a directory later swapped for a symlink, a
  managed file turned into a link, or a Neva link turned into a real file is refused, so Neva
  never deletes or rewrites through a link it did not create. Links that were already there at
  install, such as a dotfiles `~/.claude`, are part of the record and keep working.
- A JSON file that is not valid JSON, or whose top level is not an object. Missing or blank is
  treated as empty; broken is not.
- A dotted merge through a parent that holds a scalar, a list or null, and a merge entry with no key.
- An `install-state.json` that is blank, unreadable or not shaped like a manifest. Only a missing
  file means nothing is installed; anything else is refused by field name.
- A data directory, backups directory, manifest or backup file that is a symlink.
- An uninstall whose backup is missing: it fails with the backup's path and keeps the entry, so
  putting the backup back and running uninstall again restores the original.
- An uninstall over a managed file or link the owner changed after install. Its checksum is
  compared first; an edited file is kept and named, and the entry stays for a later run.
- A manifest entry whose fields contradict each other, such as a replaced file with no backup
  recorded or a merge with no previous value, before anything is removed.

Uninstall removes only the directories install created, and only while they are empty. A
directory you had before install stays, even when it is empty.

Every file Neva writes goes through an exclusively created temporary file with an unpredictable
name and an atomic rename, and keeps the mode of the file it replaces. `install.sh` refuses a
prefix or bin directory reached through a symlink, or a symlink inside the trees it replaces.

## Undo

`neva uninstall` removes exactly what that manifest owns. A shared file is never restored
wholesale from its backup, because you may have edited the rest of it since: Neva takes out its
own key, block or file, then restores the backup verbatim only when what is left parses identical
to it. A file Neva created outright is deleted and its empty directories pruned. The backups
themselves are kept.

Claude Code registrations follow the same rule. Before it registers anything, install asks the
`claude` CLI what is already there. A marketplace or plugin you had before Neva is left alone and
never recorded; one this install added is recorded, and uninstall runs `claude plugin uninstall`
or `claude plugin marketplace remove` for it. Without `claude` on PATH, uninstall names the
command to run and keeps the entry so a later run can finish the job.

`--harness <name>` scopes any of install, doctor, repair and uninstall to one harness.
`--dry-run` on install, repair and uninstall prints what would change and writes nothing.

## doctor

`neva doctor` runs `bin/doctor` for the vault, then the harness checks: every owned entry present
and unmodified, the rules present, the `NEVA_*` env set, every hook module's event registered in
`hooks.json`, `dispatch.py` runnable, the marketplace registered, a `claude` binary or
`NEVA_CLAUDE_BIN` for the nightly instinct job, and the scheduled jobs loaded. Every FAIL row
names the command that fixes it, and the exit code is 1 when anything failed. `--no-vault` skips
the first half.

## Tests

`python3 -m unittest discover -s lib/neva_cli/tests -t lib` runs the suite against a throwaway
HOME with fake harness binaries that record their argv. `build/verify.sh` section 27 runs it and
then exercises the shipped `bin/neva` as a real process, ending by asserting that HOME is byte
for byte what it was before install.
