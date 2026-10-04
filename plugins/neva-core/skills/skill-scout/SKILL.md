---
name: skill-scout
description: "Use before creating, building, forking, or installing a skill, or when asked \"is there a skill for X\": search installed, plugin, registry, GitHub, and web sources, vet external matches for risky commands, rank them, then choose use, fork, or create."
metadata:
  origin: neva (adapted from ECC, community skill)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Skill Scout

Use this skill before creating a new skill. The goal is to avoid duplicating
existing community or marketplace work, while still vetting anything external
before adoption.

Source: community contribution by `redminwang` (upstream PR #1232).

## When to Use

- The user says "create a skill", "build a skill", "make a skill", or "new
  skill".
- The user asks "is there a skill for X?" or "does a skill exist that does Y?"
- The user describes a workflow and you are about to suggest creating a new
  skill.
- The user wants to fork or extend an existing skill.

If the user explicitly says to skip search or create from scratch, acknowledge
that and proceed with the requested creation workflow.

## How It Works

### Step 1 - Capture Intent

Extract:

- The task the skill should perform.
- The trigger conditions for using it.
- The domain, tools, frameworks, or data sources involved.
- Three to five search keywords plus useful synonyms.

### Step 2 - Search Local Sources

Search installed and marketplace skill names first. Local sources are preferred
because they are already part of the user's environment.

```bash
find "$HOME/.claude/skills" .claude/skills -maxdepth 2 -name SKILL.md 2>/dev/null | grep -iE "keyword|synonym"
find "$HOME/.claude/plugins/cache" "$HOME/.claude/plugins/marketplaces" -path '*/skills/*/SKILL.md' 2>/dev/null | grep -iE "keyword|synonym"
```

Then search frontmatter descriptions:

```bash
grep -RilE "keyword|synonym" "$HOME/.claude/skills" .claude/skills "$HOME/.claude/plugins/cache" "$HOME/.claude/plugins/marketplaces" 2>/dev/null
```

Installed Neva plugins live under `plugins/cache`; their skills are invoked as `neva-<plugin>:<skill>`.

### Step 3 - Search Remote Sources

Use available GitHub and web search tools. Prefer concise queries:

```bash
gh search repos "claude code skill keyword" --limit 10 --sort stars
gh search code "name: keyword" --filename SKILL.md --limit 10
```

If Node is available, the open skills registry CLI is one more source (`npx skills find <query>`; browse skills.sh). Registry install counts and repository stars are popularity signals only: prefer 1K+ installs and known publishers, treat under 100 installs or a repo under 100 stars with extra suspicion, and still run Step 4 before recommending anything. Never install with a flag that skips confirmation.

For web search, use at most three targeted queries such as:

```text
"claude code skill" keyword
"SKILL.md" keyword
"agent skills" keyword
```

### Step 4 - Vet External Matches

Before recommending any external skill for adoption or forking:

- Read the `SKILL.md` frontmatter and instructions.
- Look for unexpected shell commands, file writes, network calls, credential
  handling, or package installs.
- Check whether the repository appears maintained.
- Prefer copying into a fresh local branch and reviewing the diff over editing
  marketplace originals.

### Step 5 - Rank Results

Rank candidates by:

1. Exact keyword match in the skill name.
2. Keyword or synonym match in description.
3. Local installed or marketplace source.
4. Maintained GitHub source with recent activity.
5. Web-only mention.

Cap the final list at 10 results.

### Step 6 - Present Decision Options

Give the user a short table:

| Option | Meaning |
| --- | --- |
| Use existing | Invoke or install a matching skill as-is. |
| Fork or extend | Copy the closest skill and modify it. |
| Create fresh | Build a new skill after confirming no close match exists. |

Only create a new skill after the user chooses that path or after the search
finds no close match.

## Examples

### Result Table

```markdown
| # | Skill | Source | Why it matches | Gap |
| --- | --- | --- | --- | --- |
| 1 | article-writing | Local plugin | Drafts articles and guides | Not focused on release notes |
| 2 | content-engine | Local plugin | Multi-format content workflow | Heavier than needed |
| 3 | blog-writer | GitHub | Blog writing skill with recent commits | Needs security review |
```

### User-Facing Summary

```markdown
I found two close local matches and one external candidate. The closest fit is
`article-writing`; it covers drafting and revision, but it does not include the
release-note checklist you asked for. I can either use it as-is, fork it into a
release-note variant, or create a fresh skill.
```

## Anti-Patterns

- Do not jump directly to new skill creation when a search is reasonable.
- Do not install external skills without reading them first.
- Do not present a long unranked list of weak matches.
- Do not treat web-only mentions as trusted sources.
- Do not edit installed marketplace originals in place.

## Related

- `search-first` - General search-before-building workflow.
- `skill-stocktake` - Audit installed skills for health, duplicates, and gaps.
- `agent-sort` - Categorize and organize existing agents and skills.
