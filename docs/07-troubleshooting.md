# Troubleshooting: real failures, real fixes

Every entry here happened on a live system. Run `doctor` first, always.

**Agent replies twice to long messages.** The Telegram polling watchdog restarts mid-turn
when a turn outlives it, and Telegram redelivers. Raise
`channels.telegram.pollingStallThresholdMs` (default 120000; 600000 for a thinking model).
Short messages unaffected = this is your issue.

**Agent goes silent on Telegram but works in terminal.** The channel lane can lock after an
aborted turn ("keeping the lane guarded" in gateway logs). Only a gateway restart clears
it. The lane-guard timer does this automatically once enabled; enable it.

**Agent starts making things up after days of chatting.** Long sessions degrade
instruction-following long before the context window fills. The session-guard timer rotates
the session on size or age. If you see invented facts, check session size before blaming
the model: ask the same question in a fresh session as the control.

**Vault sync stopped and nobody noticed.** Enable vault-sync's timer; it now alerts you on
a growing backlog and auto-quarantines gate rejections. If you see a quarantine message,
the parked commits are on a `quarantine/<date>` branch, nothing is lost.

**Local model returns empty replies.** Qwen-family thinking models write reasoning to a
separate field and leave content empty; set think:false (`params.think`). Also verify
`num_ctx`: ollama's default can silently be 4096, which truncates your system prompt away.

**getMe returned 401.** Token wrong or revoked; regenerate with BotFather.
