---
name: gateguard
description: "Use when turning on or tuning the GateGuard first-edit gate (strict hook profile), exempting paths, or answering its denial: the first Edit, Write or MultiEdit of each file is denied until the agent presents concrete facts, then the retry passes."
metadata:
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# GateGuard: Fact-Forcing First-Edit Gate

A PreToolUse hook that forces the agent to investigate before it edits. Instead of self-evaluation ("are you sure?"), it demands concrete facts. The act of investigation creates the awareness that self-evaluation never does.

## When to Activate

- Codebases where one file's edit ripples into many modules
- Projects with data files that have specific schemas or date formats
- Work where generated code must match existing patterns
- Any workflow where the agent tends to guess instead of look

## Core Concept

LLM self-evaluation does not work. Ask "did you violate any policies?" and the answer is always "no." Asking "list every file that imports this module" forces the agent to run Grep and Read, and that investigation changes the output.

```
1. DENY  - block the first edit of a file
2. FORCE - name exactly which facts to gather
3. ALLOW - the retry of that file passes
```

## Evidence

Two independent A/B tests upstream, identical agents, same task:

| Task | Gated | Ungated | Gap |
| --- | --- | --- | --- |
| Analytics module | 8.0/10 | 6.5/10 | +1.5 |
| Webhook validator | 10.0/10 | 7.0/10 | +3.0 |
| **Average** | **9.0** | **6.75** | **+2.25** |

Both agents produced code that ran and passed tests. The difference was design depth.

## What Runs

The `gateguard` module of the neva-core hook runtime (`hooks/neva_hooks/gateguard.py`), on `PreToolUse` for `Edit`, `Write` and `MultiEdit`, in the **strict** profile only. Turn it on with `NEVA_HOOK_PROFILE=strict` in your settings `env`. Bash is not gated; destructive commands are the job of `safety-guard` careful mode.

### Edit gate (first edit of an existing file; MultiEdit gates each file)

```
[Fact-Forcing Gate] Before the first edit of <file>, present these facts:
1. List ALL files that import or require this file (search the tree with Grep or Glob)
2. List the public functions, classes or endpoints this change affects
3. If the file reads or writes data, show the field names, structure and date format (synthetic values, never real records)
4. Quote the user's current instruction verbatim
```

### Creation gate (first Write of a new file)

```
[Fact-Forcing Gate] Before the first creation of <file>, present these facts:
1. Name the file(s) and line(s) that will call or load this new file
2. Confirm no existing file already serves this purpose (search the tree with Grep or Glob)
3. (data shapes, as above)
4. Quote the user's current instruction verbatim
```

Both end with: "Then retry the same operation. If this call came in a parallel batch, other edits to this file may already be applied: re-read it before building on them." and the two ways out (`GATEGUARD_EXEMPT_GLOBS`, `NEVA_GATEGUARD=off`).

After `GATEGUARD_FACT_FORCE_FULL_DENIALS` full denials (default 3) later denials condense to one line, so near-identical blocks do not pile up in a long session:

```
[Fact-Forcing Gate] (denial #N this session) First <edit|creation> of <file>: state importers or callers, affected API, data shapes if any, and the user's verbatim instruction, then retry.
```

### Always allowed

- a file already checked this session (the denial itself marks it, so the retry passes)
- `.claude/settings*.json`
- paths matching `GATEGUARD_EXEMPT_GLOBS`
- calls from a subagent (`agent_id` present): the parent already passed the gate

## Controls

| Variable | Default | Effect |
|---|---|---|
| `NEVA_HOOK_PROFILE=strict` | standard | turns the gate on |
| `NEVA_GATEGUARD=off` | on | turns it off (`0`, `false`, `off`, `disabled`, `disable`) |
| `GATEGUARD_DISABLED=1` | unset | same, `1` only |
| `NEVA_DISABLED_HOOKS=gateguard` | unset | same, at the dispatcher |
| `GATEGUARD_EXEMPT_GLOBS` | unset | comma globs that skip the gate, for low-signal trees (tests, generated files, scratch) |
| `GATEGUARD_FACT_FORCE_FULL_DENIALS` | 3 | full denials before the condensed form; `0` condenses from the first |
| `GATEGUARD_STATE_DIR` | `<NEVA_STATE_DIR>/gateguard` (`~/.local/state/neva/gateguard`) | per-session state, `<session>.json`, at most 500 checked paths |

If the state cannot be saved, the edit is allowed with a system message naming `GATEGUARD_STATE_DIR`, so the gate never loops.

Glob semantics: a relative glob matches the whole path relative to the project root (`CLAUDE_PROJECT_DIR`, else the hook's working directory); a glob starting with `/` matches the whole absolute path. `*` stays inside one segment, `**` crosses segments, `?` is one character, and `**/` includes zero directories, so `**/tests/**` also matches `tests/foo.js`. `*.md` covers only the root's Markdown files; use `**/*.md` for all of them.

```json
{
  "env": {
    "NEVA_HOOK_PROFILE": "strict",
    "GATEGUARD_EXEMPT_GLOBS": "**/tests/**,tests/**,**/*.test.*,**/docs/**,**/dist/**"
  }
}
```

## Parallel Batches and Partial Application

The gate sees one tool call at a time. When several edits to an untouched file arrive in one parallel batch, the first is denied and marks the file checked, so its siblings are applied. Nothing is rolled back: the file can hold the siblings without the denied edit.

- Send dependent edits to an untouched file one after another, not in a batch. A definition and its first use, or an import and its call site, never ride together.
- After a denial, present the facts, retry the denied edit, and re-read the file before building on anything else from the batch.

## Anti-Patterns

- **Self-evaluation instead.** "Are you sure?" always gets "yes."
- **Skipping the data schema fact.** Both A/B agents assumed ISO-8601 dates where real data used `%Y/%m/%d %H:%M`. Checking the structure (with synthetic values) prevents that whole class of bug.
- **Pre-answering the gate.** Let it fire. The investigation is what improves the result.

## Related

- `safety-guard`: careful mode asks before destructive commands; freeze keeps edits inside one directory.
- Code review agents: after the edit. GateGuard is before it.
