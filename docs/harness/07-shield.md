# Neva Shield

Neva Shield scans agent-harness configuration before it becomes an execution or data-exfiltration path. It uses Python's standard library only. Shield redacts known credential shapes and prints less by design, so a report echoes little of what it read. It is a best-effort scanner, not a proof: a credential in a shape it does not know, or a report that names something you consider private, is possible, and a clean scan does not show that a configuration is safe.

## Use it

Scan a repository in CI or from its root:

```bash
python3 bin/neva shield --path . --fail-on high
```

Scan the local configuration for supported harnesses:

```bash
python3 bin/neva shield --machine
```

Without `--path`, Shield scans local configuration. It checks Claude Code, Codex, OpenCode, Cursor, and Gemini locations. Machine output shortens files under the home directory to `~/`, and repository output names files relative to the scan root. Machine reports keep known harness names and replace every other path segment, plus server names, hosts, packages, allow rule bodies and field names, with labels such as `~/Code/project-3f2a1c9e04b7d615`, because those can identify clients and a report gets pasted around. Labels use a random key created on the first machine scan at `~/.neva/shield-label.key` with mode 600, so they stay stable between runs and a dictionary of client names cannot reverse them. If the home directory cannot hold the key, labels change on each run. `--show-paths` prints the real names for you to work through.

Formats:

```bash
python3 bin/neva shield --path . --format text
python3 bin/neva shield --path . --format json
python3 bin/neva shield --path . --format sarif
```

SARIF is version 2.1.0 and can be uploaded to GitHub code scanning. `--fail-on high` fails for high and critical findings. `--fail-on medium` also fails for medium findings.

Exit codes: 0 when the scan read configuration and nothing reached the threshold, 1 when a finding did, 2 when the scan could not vouch for the tree. A scan that found no harness configuration exits 2 with no grade, because nothing was checked.

## What Shield checks

- Permissions: unrestricted Bash permissions, file upload permissions, broad writes under home, WebFetch combined with upload, and settings with no secret-path deny list.
- Bypasses: skip-permission flags, approval bypasses, unsafe Codex approval and sandbox pairs.
- Hooks: unquoted payload interpolation, download-and-execute commands, network egress, swallowed blocked actions, and world-writable scripts.
- MCP: unpinned `npx` or `uvx`, HTTP servers without configured authentication, and inline environment credentials. Findings name the environment key only.
- Secrets: token, key, and private-key material in settings and agent instructions, including literal `Authorization`, `X-API-Key`, and similar headers. Values are redacted from every format. Reports echo only what is recognizably safe: a shell allow rule prints as `Bash(curl ...)`, another tool prints its body only when that is a wildcard or a plain path, and a package prints by host if it is a URL, by name if it is plainly one, and otherwise as `<package>`.
- Prompt injection: Unicode direction controls, instruction overrides, large encoded blobs, and download-and-execute instructions in skills, agents, commands, and rules.
- Provenance: non-HTTPS or unpinned plugin marketplaces and credential files readable by group or other users.

Shield only reads configuration files, apart from the machine label key above, and never follows a symlink. In a repository scan, a symlink to a directory stops the scan with exit 2 and names the link, unless the link itself has an ignored name such as `node_modules`. So does a symlink or a special file such as a FIFO in place of a recognized configuration file, because anyone can commit a link and it would hide configuration from the gate.

On a machine the owner made the links and the harness relies on them, so `--machine` reports them and carries on, without reading a target. A link at a harness location inside a checkout is high, because a clone carries it to every machine. Any other directory link under a code home is medium, as is a link standing in for a whole harness location, a `hooks` or instruction folder, or a settings, MCP, hook, credential, instruction or marketplace file. Those are LINK001. Any other link is LINK002: low, listed once in the text report, and left out of the grade, since a machine with many linked skills is not a worse machine. A skipped harness location caps the score at 89, so it never grades A. To check a target, run `--path` on the real directory.

`--out` creates a new report inside the scan root, or inside the current directory for machine scans. Existing files and paths containing symlinks are refused. Every finding names an ID, severity, file and line, plus a specific corrective change. The grade is A through F from a weighted score: critical findings subtract 30 points, high 15, medium 6, low 2.

## Scope

Repository scans inspect recognized configuration files in `.claude`, `.codex`, `.opencode`, `.cursor`, and `.gemini`, along with `CLAUDE.md`, `AGENTS.md`, settings, MCP configuration, hook files, credential files, and instruction markdown under skills, agents, commands, and rules. Shield's own deliberately malicious test fixtures are excluded from whole-repository scans only.

Build and cache folders such as `dist`, `vendor`, `target` and `tmp` are skipped, except inside a harness folder: `.claude`, `.codex`, `.cursor`, `.gemini`, `.opencode`, `skills`, `agents`, `commands`, `rules`, `prompts`, `hooks`, `plugins` or `.claude-plugin`. The harness loads what sits there, so `.claude/skills/tmp` is scanned, and a link there blocks like any other. `node_modules`, `__pycache__`, `.venv`, `venv` and `site-packages` are skipped outside harness folders and below a skill's own root such as `.claude/skills/one/node_modules`. Directly under `skills`, or anywhere under `commands`, `agents` or `rules`, they are scanned, because Claude Code loads them. `.git` is skipped everywhere. A skipped name that holds a `.claude-plugin` folder is scanned anyway. Folders are judged by their path below the scan root and the root's own name, so where a repository was cloned cannot change the result, but a checkout named `skills` or `hooks` is treated as that harness folder.

| Configuration | Runtime requirement |
|---|---|
| Codex TOML | Python 3.11 or newer. An unavailable TOML parser blocks the scan. |
