# First run: terminal only

Get to a working conversation BEFORE touching Telegram or timers. Everything else builds on
this; if this step works, every later problem is isolated to the layer you just added.

1. Install openclaw (macOS/Linux): follow https://docs.openclaw.ai/install (Node 22+).
2. Run `./install.sh` from this folder. Answer the three identity questions (name, agent name,
   timezone). It ends with `doctor`.
3. Fix anything doctor marks FAIL (each row names its fix). WARNs are fine for now.
4. Start the gateway, then open a terminal chat with your agent:
   `openclaw agent --agent main --message "hello"`
5. Your agent's first conversation is the BOOTSTRAP setup interview: it asks six questions,
   one at a time, writes what it learns into files you can open and edit, and ends by asking
   for a real task. Give it one.

Success = it answered your real task and USER.md exists in the workspace. Only then move to
[02-telegram.md](02-telegram.md).

Vault structure: [docs/04-vault-and-canon.md](04-vault-and-canon.md) explains how notes are
organized and discovered.

Troubleshooting: run `doctor` first, always. It names the broken layer.
