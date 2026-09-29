# MCP budget

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->
Source: distilled from Affaan Mustafa's Everything Claude Code guides (the shortform, longform and security guides) and the upstream MCP connector policy.

Every MCP tool schema loads into every session whether you use it or not. Be picky. The canonical process is [process.md](../../plugins/neva-core/rules/process.md).

## Budget

| Limit | Value |
|-------|-------|
| Servers in config | 20 to 30 is fine |
| Servers enabled at once | under 10 |
| Tools active at once | under 80 |
| Typical enabled per project | 5 to 6 |
| Cost per tool schema | about 500 tokens |
| Flag a single server with | more than 20 tools |
| Default servers shipped | well under 10; the field norm is 0 to 2 plus built-ins |

What overload looks like: a 200k window can shrink to about 70k usable before compaction when too many tools are enabled, and quality drops well before that. One 30-tool server costs more than all your skills combined.

## The connector rule

A server earns a default slot only when both hold:

1. Universal: it applies to essentially every user, on every harness Neva targets.
2. MCP beats a CLI or API wrapped in a skill: the job genuinely needs a held-open session, streaming, an auth handshake, or structured browsing.

Stateless request and response work is a skill, not a server. "Popular" is not an argument for a slot. "The job is stateful and universal" is.

To propose a new default, argue both prongs explicitly.

## Default set

| Server | Why it passes |
|--------|---------------|
| `chrome-devtools` | Google's official DevTools server. Live debugging, performance traces, console and network inspection on a stateful browser. The value is the open session, not a one-shot command. Keyless. |

## What replaced the former defaults

| Former default | Verdict | Replacement |
|----------------|---------|-------------|
| `github` | skill | the `gh` CLI in a skill. The server's roughly 30 tool schemas taxed every session. `gh` composes one-shot commands with little overhead and authenticates once. |
| `context7` | skill | a docs-lookup skill calling the public REST API: two stateless calls, no session to justify a server. |
| `exa` | skill | the harness's native web search by default. A search skill remains for key holders. Needing a key fails the universality test. |
| `memory` | drop | native harness memory plus the instinct system in [03-memory-and-learning.md](03-memory-and-learning.md). |
| `playwright` | skill | the Playwright CLI. Returning a full accessibility tree per step burns context; the vendor moved agent workflows off MCP for that reason. Interactive browser debugging is covered by `chrome-devtools`. |
| `sequential-thinking` | drop | native extended thinking. It wrapped no external system. |

All six stay available as opt-in entries.

## Replace wrappers with CLI skills

Most platform servers (code hosting, databases, deploy targets) wrap a CLI that already exists. Strip out the few operations you actually use and make them commands or skills:

- instead of a resident GitHub server, a `/gh-pr` command around `gh pr create` with your preferred flags
- instead of a database server, skills that call that database's CLI directly

Lazy tool loading solves most of the window problem. It does not solve token cost. The CLI plus skill approach still wins on cost.

## Enable per project

- Keep every server in user config. Disable everything the current project does not use.
- Check what is live with `/mcp`, or the plugins view.
- Per-project overrides: `disabledMcpServers` in the project config, or the project's `.mcp.json`.
- Neva's generated configs honour an opt-out list at install and sync:

```bash
export NEVA_DISABLED_MCPS="chrome-devtools"
```

- Plugins carry the same cost. Keep 4 to 5 enabled at a time.

## Opt-in catalog: free candidates

Enable per project, never globally. Every entry below is free to use at the level listed.

| Server | Job | Needs |
|--------|-----|-------|
| `chrome-devtools` | stateful browser debugging | nothing |
| `context7` | live library docs | nothing (a key raises limits) |
| `cloudflare-docs` | platform docs search | nothing |
| `playwright` | browser automation when the CLI is not enough | nothing |
| `github` | PRs, issues, repos, if a skill will not do | a scoped token |
| `supabase`, `vercel`, Cloudflare Workers servers | per-project platform ops | an account on that platform's free tier |

Servers that require a paid account or paid API usage are not part of Neva's catalog. Add them yourself, per project, when you already pay for the service.

## Security

MCP is part of the attack surface (see [05-security.md](05-security.md)):

- A tool description, schema or output can carry instructions. Treat all three as untrusted.
- Never auto-approve project-scoped servers. Watch for `enableAllProjectMcpServers` in repo-controlled settings.
- A server can exfiltrate data while appearing to return exactly what was asked.
- Read a server's config and source before enabling it, the same as a skill.

## Audit

After adding any server, count its tools, multiply by about 500, and check the totals against the budget table. Remove CLI-replaceable servers first. Full procedure in [02-token-economy.md](02-token-economy.md).
