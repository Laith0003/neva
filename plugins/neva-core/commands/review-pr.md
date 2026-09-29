---
description: "Comprehensive PR review using specialized agents"
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

Run a comprehensive multi-perspective review of a pull request.

## Usage

`/review-pr [PR-number-or-URL] [--focus=comments|tests|errors|types|code|simplify]`

If no PR is specified, review the current branch's PR. If no focus is specified, run the full review stack.

## Steps

1. Identify the PR:
   - use `gh pr view` to get PR details, changed files, and diff
2. Find project guidance:
   - look for `CLAUDE.md`, lint config, TypeScript config, repo conventions
3. Run specialized review agents:
   - `neva-core:code-reviewer`
   - `neva-core:comment-analyzer`
   - `neva-core:pr-test-analyzer`
   - `neva-core:silent-failure-hunter`
   - `neva-core:type-design-analyzer`
   - `neva-core:code-simplifier`
4. Aggregate results:
   - dedupe overlapping findings
   - rank by severity
5. Report findings grouped by severity

## Confidence Rule

Only report issues with confidence >= 80:

- Critical: bugs, security, data loss
- Important: missing tests, quality problems, style violations
- Advisory: suggestions only when explicitly requested
