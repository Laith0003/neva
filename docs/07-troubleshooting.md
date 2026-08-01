# Troubleshooting: find your error and fix it

Every entry below happened on a live system. Run `doctor` first, always; it names the
broken layer before anything else.

## By error message (search your logs for the exact string)

| Error in logs | Cause | Fix |
|---|---|---|
| `getMe returned 401` | Telegram bot token wrong or revoked | Regenerate token: open Telegram, search @BotFather, send /newbot, copy the token, update ~/.openclaw/openclaw.json |
| `channel lane locked` | Gateway lane blocked after an aborted turn | Restart the gateway: `openclaw gateway` in a new terminal. Lane-guard timer automates this; enable it: docs/03-scheduled-jobs.md |
| `connection refused` (on 127.0.0.1:18789) | Gateway not running | Start it: `openclaw gateway` in a terminal |
| `ENOTFOUND api.telegram.org` | Network connectivity issue | Check your internet connection; if connected, Telegram servers may be down |

## By symptom (if you don't see an exact error string)

**Agent replies twice to the same message on Telegram**

The polling watchdog restarts mid-turn when a slow turn outlives it (default 120 seconds),
and Telegram re-delivers the message. Short messages unaffected = this is your issue.

Fix: Raise `channels.telegram.pollingStallThresholdMs` in ~/.openclaw/openclaw.json:
```json
"channels": {
  "telegram": {
    "pollingStallThresholdMs": 600000
  }
}
```
Restart the gateway after editing.

**Agent goes silent on Telegram but works in terminal**

The channel lane can lock after an aborted turn; you see this in gateway logs as "keeping
the lane guarded". Only a gateway restart clears it.

Fix: Restart the gateway. Automate it by enabling the lane-guard timer:
docs/03-scheduled-jobs.md, recommended order.

**Agent starts making things up after days of chatting**

Long sessions degrade instruction-following long before the context window fills. The agent
invents facts when it should say "I don't have that".

Fix: Enable session-guard timer (docs/03) to rotate the session on size or age. To verify
this is your issue: ask the same question in a fresh terminal session (new agent process) as
a control. If the fresh session answers correctly, session bloat is the cause.

**Vault sync stopped and nobody noticed**

The git backlog grows silently until vault-sync notices it, then it quarantines the commits
to avoid a merge conflict.

Fix: Enable vault-sync timer (docs/03, recommended first). If you see a quarantine message,
the parked commits are on a `quarantine/<date>` branch; nothing is lost. Git will tell you
what to do when you sync again.

**Local model returns empty replies**

Qwen-family thinking models write reasoning to a separate field and leave content empty.
Also check num_ctx: ollama's default is 4096, which silently truncates your system prompt.

Fix: Set `params.think: false` in your model config. Verify `num_ctx: 8192` or higher in
ollama. Test with `ollama show model_name` to see current settings.

**Doctor shows "all clear" but agent is not working**

Doctor reports on broken things, not on inert things. You may need to:
- Start the gateway: `openclaw gateway`
- Enable a scheduled timer: docs/03-scheduled-jobs.md
- Complete Telegram setup: docs/02-telegram.md

Read the full output of doctor, especially the "config is healthy, but your assistant
cannot work yet" section. Each item lists what you have not done yet, not what is broken.

---

Run `doctor` any time to get a fresh status report. Every row names its fix.
