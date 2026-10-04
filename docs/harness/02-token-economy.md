# Token economy

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->
Source: distilled from Affaan Mustafa's Everything Claude Code guides (the shortform and longform guides).

Context is the scarcest resource in a session. Every rule on this page protects it. The canonical process is [process.md](../../plugins/neva-core/rules/process.md).

## Rules at a glance

| Rule | Number |
|------|--------|
| Stay out of the last part of the window for multi-file work | last 20% |
| Suggest compaction at | 160k tokens on a 200k window, 800k on a 1M window |
| Repeat the suggestion every | 60k more tokens |
| Tool-call fallback signal | first at 50 calls, then every 25 |
| MCP servers enabled at once | under 10 |
| Active tools | under 80 |
| Cost of one tool schema | about 500 tokens |
| Parallel tasks held at once | 3 to 4 |

## Model routing

Rule: send each task to the cheapest model that is sufficient, and pin the model in the agent's frontmatter so the choice is not re-made every time.

Neva's pins:

| Pin | Use for | Examples |
|-----|---------|----------|
| opus | judgment | planning, architecture, every reviewer, security, evaluators, researchers, complex debugging |
| sonnet | mechanical work | build-error resolvers, refactor cleaners, doc updaters, packagers, multi-file implementation from a written plan |
| haiku | pure lookup | docs lookup, file finding |

Why: the upstream guide's own routing table puts security analysis and complex debugging on the strongest model because missing a vulnerability costs more than the tokens. Neva extends that to every reviewer.

Escalate to opus when any of these hold, even for work that is normally mechanical:

- the first attempt failed
- the task spans 5 or more files
- an architectural decision is involved
- the code is security-critical

Upstream reference points, kept for context:

| Upstream claim | Value |
|----------------|-------|
| Haiku relative to Sonnet | about 90% of the capability at about a third of the cost |
| Share of coding work upstream sends to Sonnet by default | 90% |
| Extended thinking reserve | up to 31,999 tokens |
| Example thinking cap | `MAX_THINKING_TOKENS=10000` |

## Context window budget

Rule: avoid the last 20% of the window for work that needs the whole picture.

| Sensitive to a full window | Tolerates a full window |
|----------------------------|-------------------------|
| large refactors | single-file edits |
| features spanning multiple files | independent utility creation |
| debugging complex interactions | documentation updates |
| | simple bug fixes |

Why: as the window fills, the model loses file paths, variable names and earlier decisions, and quality drops before any hard limit is reached.

What fills the window:

| Component | Load behaviour | Budget note |
|-----------|----------------|-------------|
| CLAUDE.md chain | always loaded | flag a combined total over 300 lines |
| Agent descriptions | present in every delegation call, even if the agent is never used | flag descriptions over 30 words |
| Agent bodies | loaded on each spawn | flag files over 200 lines |
| Skills | 1K to 5K tokens each when loaded | flag files over 400 lines |
| Rules | always loaded | flag files over 100 lines |
| MCP tools | about 500 tokens per tool schema | flag servers over 20 tools |
| Tool results | file reads and search output | the silent bulk |

Estimate tokens as words times 1.3 for prose, characters divided by 4 for code-heavy files.

Duplicate context to hunt down: the same rule in both user and project rules folders, skills that restate CLAUDE.md, several skills covering one domain.

Lazy loading: a trigger table that maps keywords to skill paths, so a skill loads only when its trigger appears, cuts baseline context by 50% or more.

## Strategic compaction

Rule: compact at milestones, never mid-implementation. Write state to a file before you compact.

Why: automatic compaction fires at arbitrary points, often mid-task, with no awareness of task boundaries. A planned compaction keeps the distilled output and drops the bulk.

| Phase transition | Compact? | Why |
|------------------|----------|-----|
| Research to planning | Yes | research is bulky, the plan is the distilled output |
| Planning to implementation | Yes | the plan is on disk, free the window for code |
| Implementation to testing | Maybe | keep if tests reference recent code, compact if switching focus |
| Debugging to next feature | Yes | debug traces pollute unrelated work |
| Mid-implementation | No | losing paths, names and partial state is costly |
| After a failed approach | Yes | clear dead-end reasoning before the next attempt |

What survives:

| Persists | Lost |
|----------|------|
| CLAUDE.md instructions | intermediate reasoning |
| files on disk | file contents you read earlier |
| memory files | multi-step conversation context |
| git state | tool history and counts |
| the task list, only on harnesses that still ship task tools | preferences you stated verbally |

Mechanics of the compaction hook (`suggest_compact`, PreToolUse on Edit, Write and MultiEdit, standard and strict profiles; see [hooks.md](hooks.md)):

1. Primary signal, context size: read the latest usage record from the transcript and sum input, cache-read and cache-creation tokens. Suggest compaction at 160k on a 200k window or 800k on a 1M window, then again after every further 60k.
2. Fallback signal, edit count, used only while the transcript has no usage record yet: suggest at 50 edits, then every 25. Count alone is a weak proxy: a few large reads can fill the window in a handful of calls.
3. The hook says when. You decide if.

| Setting | Default |
|---------|---------|
| `COMPACT_THRESHOLD` | 50 edits (fallback only) |
| `COMPACT_CONTEXT_THRESHOLD` | 160000 (200k window), 800000 (1M window), `0` disables |
| `COMPACT_CONTEXT_INTERVAL` | 60000 |
| `COMPACT_STATE_TTL_DAYS` | 14 (age at which per-session hook state in `~/.local/state/neva/hooks/` is pruned) |
| `NEVA_CONTEXT_WINDOW_TOKENS` | unset; set it for large-window models whose id does not reveal the window |

Best practice: compact with a focus line, for example `/compact Focus on implementing auth middleware next`. After a plan is final, clearing context and working from the plan file is often better than compacting at all.

## Subagent context isolation

Rule: push exploration and bulky reads into subagents that return summaries.

Why: a subagent's reads never enter the main window. Only its answer does.

The cost: the subagent knows the literal query, not the purpose. Pass the objective, not just the question, and evaluate every return before accepting it. The retrieval loop and its limits are in [04-parallelism.md](04-parallelism.md).

## Dynamic context injection

Rule: load mode-specific context only when the mode is active.

Why: everything in CLAUDE.md or the rules folder loads every session. Content passed as a system prompt has higher authority than user messages, which have higher authority than tool results.

```bash
alias neva-dev='claude --system-prompt "$(cat contexts/dev.md)"'
alias neva-review='claude --system-prompt "$(cat contexts/review.md)"'
alias neva-research='claude --system-prompt "$(cat contexts/research.md)"'
```

Neva ships these contexts under `plugins/neva-core/contexts/`.

## Cost levers

In order of impact:

1. MCP servers. The biggest lever: a 30-tool server costs more than all your skills combined. Keep under 10 enabled and under 80 tools. See [06-mcp-budget.md](06-mcp-budget.md).
2. Replace MCP wrappers with CLI skills. Lazy loading solves most of the window problem but not token cost. A small command that wraps `gh pr create` costs far less than a resident GitHub server.
3. Model routing, per the table above.
4. Subagents for exploration.
5. Modular code. Files in the hundreds of lines, not thousands, cost less to read and are more often right the first time.
6. Search tooling. Semantic search tools can cut search tokens; upstream reports roughly half the tokens of grep-based search in a 50-task benchmark. Measure before adopting.
7. Plugins, same warning as MCP: upstream keeps 4 to 5 enabled at a time.

## Audit

Run a context budget audit after adding any agent, skill, rule or MCP server. It inventories each component, classifies it (always needed, sometimes needed, rarely needed), flags the thresholds above, and ranks fixes by tokens saved.
