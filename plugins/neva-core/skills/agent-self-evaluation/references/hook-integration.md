# Hook Integration for Session-Stop Self-Evaluation

hook: ported separately (Python). This file describes the contract only. Do not add hook code or hooks.json entries from this skill.

## Contract 1: Stop reminder

| Field | Value |
|---|---|
| Event | `Stop` (no matcher needed; matcher is optional for `Stop`, `Notification`, `UserPromptSubmit`, `SubagentStop`) |
| Input | Standard Stop hook JSON on stdin (ignored) |
| Behaviour | Prints one reminder line, never blocks (exit 0) |
| Output | `[Self-Eval] Session complete. Consider running agent-self-evaluation to rate your output.` |
| Writes | Nothing |

The hook echoes a reminder. It does not run the evaluator.

## Contract 2: PostToolUse reminder after shell verification

| Field | Value |
|---|---|
| Event | `PostToolUse`, matcher `Bash` |
| Input | PostToolUse JSON on stdin; the hook may inspect `tool_input.command` |
| Filter | Only fire when the command matches a word-boundary regex such as `\b(pytest|npm test|go test)\b`, never a bare `test` substring |
| Behaviour | Prints one reminder line, never blocks (exit 0) |
| Output | `[Self-Eval] If this command completed verification for a non-trivial task, consider running agent-self-evaluation.` |
| Writes | Nothing |

Both hooks are opt-in.

## The Python Evaluator

`scripts/evaluate.py` is a standalone tool:

```bash
# Pipe agent output directly
echo "Your agent response here" | python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-self-evaluation/scripts/evaluate.py"

# From files
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-self-evaluation/scripts/evaluate.py" --task task.txt --output response.txt
```

To drive it from a hook, the hook must first capture the last agent output to a file, then run the evaluator on that file.

## Manual Usage (Recommended)

The most reliable approach is manual invocation: the agent runs self-evaluation as part of its workflow when the `agent-self-evaluation` skill is active, without requiring hook configuration. The skill's "When to Activate" section already covers trigger conditions (multi-file changes, debugging sessions, design documents).
