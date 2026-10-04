---
name: cost-tracking
description: Use when the user asks about Claude Code token usage, spend, budgets, or cost breakdowns by model, session or date. Reads the local cost log written by the Neva cost-tracker hook.
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Cost Tracking

Use this skill to analyze Claude Code cost and usage history from the metrics log
that the Neva cost-tracker Stop hook writes.

## Where the data lives

The tracker appends one JSON object per session-stop to
`${NEVA_METRICS_DIR:-~/.local/share/neva/metrics}/costs.jsonl`. Each row is a **cumulative snapshot for that
session**, so to total spend you take the **latest row per `session_id`** and
sum across sessions, summing every row multiply-counts.

The writer is the `cost_tracker` module of the neva-core hook runtime (Stop,
standard and strict profiles). It appends a row only when the session's usage
changed since its last row. Folder resolution, identical in the hook, this
skill and `/cost-report`: `NEVA_METRICS_DIR`, else `<data dir>/metrics` where the
data dir is `NEVA_DATA_DIR`, else `$XDG_DATA_HOME/neva`, else `~/.local/share/neva`.

Row schema:

| Field | Meaning |
| --- | --- |
| `timestamp` | ISO timestamp of the snapshot |
| `session_id` | Claude Code session identifier |
| `transcript_path` | Path to the session transcript |
| `project` | Project name (git toplevel basename) |
| `model` | Model used |
| `input_tokens` / `output_tokens` | Token counts |
| `cache_write_tokens` / `cache_read_tokens` | Prompt-cache token counts |
| `estimated_cost_usd` | Precomputed cumulative cost in USD for the session |

Prefer `estimated_cost_usd` over hand-calculating pricing, model and cache
prices change, and the tracker is the source of truth.

## When to Use

- The user asks "how much have I spent?", "what did this session cost?", or
  "what is my token usage?"
- The user mentions budgets, spending limits, overruns, or cost controls.
- The user wants a cost breakdown by model, session, or date, or a CSV export.

## How It Works

The log path is `$NEVA_METRICS_DIR/costs.jsonl`, defaulting to `~/.local/share/neva/metrics/costs.jsonl`. First verify it exists:

```bash
python3 - <<'EOF'
import os
d = os.environ.get("NEVA_METRICS_DIR") or os.path.join(os.environ.get("NEVA_DATA_DIR") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "neva"), "metrics")
f = os.path.join(os.path.expanduser(d), "costs.jsonl")
print("cost log found: " + f if os.path.exists(f) else f"cost log not found: {f}")
EOF
```

If the log is missing, do not fabricate usage data. Tell the user that cost
tracking populates after the first response ends with the neva-core
`cost_tracker` hook enabled (standard or strict profile).

## Example: summary and by-model breakdown

```bash
python3 - <<'EOF'
import os, json, datetime as dt, collections
d = os.environ.get("NEVA_METRICS_DIR") or os.path.join(os.environ.get("NEVA_DATA_DIR") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "neva"), "metrics")
f = os.path.join(os.path.expanduser(d), "costs.jsonl")
if not os.path.exists(f): print(f"cost log not found: {f}"); raise SystemExit
rows = []
for line in open(f, encoding="utf-8").read().splitlines():
    try: rows.append(json.loads(line))
    except Exception: pass
latest = {}
for r in rows:  # rows are cumulative per session: keep the newest per session
    k = r.get("session_id") or r.get("transcript_path") or r.get("timestamp")
    if k not in latest or str(r.get("timestamp")) > str(latest[k].get("timestamp")): latest[k] = r
L = list(latest.values()); cost = lambda r: float(r.get("estimated_cost_usd") or 0)
day = lambda r: str(r.get("timestamp", ""))[:10]
today = dt.date.today().isoformat(); yest = (dt.date.today() - dt.timedelta(days=1)).isoformat()
f4 = lambda n: f"${n:.4f}"
print(f"today: {f4(sum(cost(r) for r in L if day(r)==today))} | yesterday: {f4(sum(cost(r) for r in L if day(r)==yest))} | total: {f4(sum(map(cost, L)))} ({len(L)} sessions)")
by = collections.Counter()
for r in L: by[r.get("model") or "(unknown)"] += cost(r)
print("by model:"); [print(f"  {f4(v)}  {k}") for k, v in by.most_common()]
EOF
```

For a session drilldown or CSV export, iterate the same `latest` set (or the raw
rows for CSV) and print the fields you need.

## Reporting Guidance

When presenting cost data, include today's spend vs yesterday, total across all
sessions, a by-model breakdown, and session count. Format sub-dollar amounts
with four decimals, larger amounts with two.

## Anti-Patterns

- Do not sum every row, they are cumulative per session; reduce to the latest
  row per `session_id` first.
- Do not estimate costs from raw token counts when `estimated_cost_usd` is present.
- Do not assume the log exists without checking.
- Do not hard-code current model pricing in user-facing answers.
- Do not recommend installing unreviewed hooks or plugins that execute arbitrary code.

## Related

- `/cost-report` - Command-form report over the same metrics log.
- `cost-aware-llm-pipeline` - Model-routing and budget-design patterns.
- `token-budget-advisor` - Context and token-budget planning.
- `strategic-compact` - Context compaction to reduce repeated token spend.
