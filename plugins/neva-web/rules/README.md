<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# neva-web Rules

## Structure

Rules are layered: a **common** layer that ships at the top of `neva-core/rules/`, plus **language and framework** directories that ship here in `neva-web`.

```
neva-core/rules/     # Language-agnostic principles (always on)
├── coding-style.md
├── git-workflow.md
├── testing.md
├── performance.md
├── patterns.md
├── hooks.md
├── agents.md
└── security.md

neva-web/rules/
├── typescript/      # TypeScript and JavaScript
├── react/           # React
├── angular/         # Angular
├── vue/             # Vue 3
├── nuxt/            # Nuxt 4
├── php/             # PHP and Laravel
├── ruby/            # Ruby and Rails
└── web/             # Web and frontend: style, design quality, RTL, performance, security, testing
```

- The `neva-core` rules hold universal principles with no language-specific code.
- Each language directory extends its common counterpart with framework patterns, tools, and examples. Every file links its common file as `../common/<name>.md`, which resolves in the installed layout (`~/.claude/rules/neva/common/` next to `~/.claude/rules/neva/<lang>/`).
- Each rule file declares `paths:` globs in its frontmatter so it loads only for matching files (for example `**/*.php` or `**/*.blade.php`).

## Installation

Claude Code does not load rules from inside a plugin. Neva's install step copies `neva-core/rules/*.md` to `~/.claude/rules/neva/common/` and each language folder you need to `~/.claude/rules/neva/<lang>/`; see `neva-core/rules/README.md` for the table and the manual commands. Never flatten directories: files share names across languages and would overwrite each other.

## Rules vs Skills

- **Rules** define standards, conventions, and checklists that apply broadly (for example "tests never touch the dev database", "logical properties only").
- **Skills** provide deep, task-specific reference (for example `laravel-tdd`, `react-patterns`).

Rules say _what_ to do; skills say _how_.

## Adding a New Language

1. Create `rules/<lang>/`.
2. Add files that extend the common rules:
   - `coding-style.md`: formatting tools, idioms, error handling
   - `testing.md`: framework, coverage, organization, test-database isolation
   - `patterns.md`: language design patterns
   - `hooks.md`: formatters, linters, type checkers to run after edits
   - `security.md`: secret management, scanning tools
3. Start each file with `paths:` frontmatter and:
   ```
   > This file extends [common/xxx.md](../common/xxx.md) with <Language> specific content.
   ```
4. Reference existing skills, or add new ones under `skills/`.

## Rule Priority

When a language rule and a common rule conflict, the **language rule wins** (specific overrides general), the same way CSS specificity or `.gitignore` precedence works. A project's own `CLAUDE.md` and design system outrank both.

Example: common `coding-style.md` recommends immutability. Idiomatic Go uses pointer receivers for struct mutation, so a Go rule may override it and say so explicitly.

Common rules that a language may override carry this marker:

> **Language note**: This rule may be overridden by language-specific rules for languages where this pattern is not idiomatic.
