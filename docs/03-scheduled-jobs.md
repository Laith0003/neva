# Scheduled jobs: enable one at a time

install.sh rendered them to `~/.local/lucy/services/` but enabled NOTHING. Turn each on
alone, watch it once, then add the next. Debug layers sequentially, never simultaneously.

Recommended order: vault-sync (2 min), then canon-lint (daily), then cadence (daily), then
session-guard + lane-guard (2 min), then vault-mirror (hourly), then diag (weekly).

macOS: `cp ~/.local/lucy/services/com.lucy.<name>.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.lucy.<name>.plist`
Linux: `cp ~/.local/lucy/services/lucy-<name>.{service,timer} ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now lucy-<name>.timer`

Check: doctor shows the loaded count; each tool logs to `~/.local/state/lucy/`.

What each does: vault-sync moves agent writes between machines through git; canon-lint
checks people notes daily and messages you on real errors; cadence notices stale reviews or
journal and offers to draft; session-guard rotates the chat session before long-context
degradation makes the agent less accurate; lane-guard restarts the gateway if the Telegram
lane ever locks; vault-mirror keeps memory search fresh; diag runs the weekly self-test and
sends you the score.
