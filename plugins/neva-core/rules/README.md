<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->
# Neva Rules

Rules are standards that apply to every session: what to do, what never to do, and the gates in between. Skills say how; rules say what.

## Plugins cannot load rules

A Claude Code plugin can ship skills, agents, commands, hooks and MCP servers. It cannot ship rules: Claude Code reads rules only from `~/.claude/rules/` (user level) and `.claude/rules/` (project level). A rules folder inside a plugin is inert until something copies it out.

So Neva's install step copies them. It never edits your own rule files.

## Where install puts them

Everything goes under one namespace, `~/.claude/rules/neva/`, so Neva never collides with rules you wrote yourself or rules from another pack.

| Source in this repo | Installed to |
|---------------------|--------------|
| `plugins/neva-core/rules/*.md` (this folder) | `~/.claude/rules/neva/common/` |
| `plugins/neva-web/rules/<lang>/` | `~/.claude/rules/neva/<lang>/` |
| `plugins/neva-mobile/rules/<lang>/` | `~/.claude/rules/neva/<lang>/` |
| `plugins/neva-backend-langs/rules/<lang>/` | `~/.claude/rules/neva/<lang>/` |

Install copies whole directories. Do not flatten them: common and language folders share filenames (`coding-style.md`, `testing.md`, `hooks.md`), and flattening lets a language file overwrite its common counterpart. Language files link to their counterpart as `../common/<file>.md`, which resolves only in the installed layout.

Install copies `common/` always, and a language folder only when you ask for it or when the project in front of you uses that language. Upgrades replace the `neva/` folder wholesale, so do not edit files inside it: put your own rules next to it in `~/.claude/rules/`.

Manual install, if you prefer it:

```bash
mkdir -p ~/.claude/rules/neva/common
cp plugins/neva-core/rules/*.md ~/.claude/rules/neva/common/
cp -r plugins/neva-web/rules/typescript ~/.claude/rules/neva/
cp -r plugins/neva-backend-langs/rules/python ~/.claude/rules/neva/
```

For project-level rules, use the same layout under the project: `.claude/rules/neva/common/`, `.claude/rules/neva/<lang>/`.

`README.md` files are documentation; install skips them.

## What is in common

| File | Covers |
|------|--------|
| [process.md](process.md) | **The canonical loop**: size up, research, plan with a confirm gate, tests first, implement, fresh-context review, verify with evidence, remember, improve. Human checkpoints and conductor posture. Read this first. |
| [development-workflow.md](development-workflow.md) | The feature pipeline in short form |
| [agents.md](agents.md) | Which agent when, team-first dispatch, parallel limits, the completion contract |
| [code-review.md](code-review.md) | Review triggers, fresh-context and dual independent review, severity |
| [testing.md](testing.md) | 80% coverage, the RED gate, test isolation, proving checks can fail |
| [coding-style.md](coding-style.md) | Immutability, file size, specific errors, validation |
| [security.md](security.md) | Pre-commit checks, secrets, human checkpoints, untrusted input |
| [performance.md](performance.md) | Model routing and escalation, context budget, compaction |
| [hooks.md](hooks.md) | Hooks over reminders, hook types, writing good hooks |
| [patterns.md](patterns.md) | Skeleton projects, real assets, repository and response patterns |
| [git-workflow.md](git-workflow.md) | Commit format, git safety, PR flow |

## Precedence

1. What the human says in the conversation.
2. The human's own rules (`~/.claude/rules/*.md` outside `neva/`, project `CLAUDE.md`).
3. Neva language rules (`neva/<lang>/`): specific overrides general.
4. Neva common rules (`neva/common/`), with `process.md` winning inside common.

Common rules that a language may override carry a **Language note**.

## Conditional loading

Language rule files start with a `paths:` frontmatter block of globs, so they apply only when matching files are in play. Common rules have no `paths:` and apply everywhere.

## Adding a language

1. Create `plugins/<plugin>/rules/<lang>/`.
2. Add files that extend the common rules: `coding-style.md`, `testing.md`, `patterns.md`, `hooks.md`, `security.md`.
3. Start each with a `paths:` block, the adaptation comment if ported, then:
   `> This file extends [common/<file>.md](../common/<file>.md) with <Language> specific content.`
4. Reference existing skills where they exist.
