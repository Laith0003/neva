# Scheduled jobs: enable one at a time

install.sh renders every job template to `~/.local/neva/services/` but does not enable most
of them. It DOES ask, once, whether to turn on the one flagship timer (cadence, the
review-nudge) - default answer NO, so a plain `Enter` or a non-interactive install leaves it
off, same as everything else here. Turn the rest on alone, watch each once, then add the
next. Debug layers sequentially, never simultaneously; enabling everything at once is a
documented way these break.

Recommended order: vault-sync (2 min), then canon-lint (daily), then cadence (daily), then
session-guard + lane-guard (2 min), then vault-mirror (hourly), then diag (weekly).

## Enable

macOS: `cp ~/.local/neva/services/com.neva.<name>.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.neva.<name>.plist`
Linux: `cp ~/.local/neva/services/neva-<name>.{service,timer} ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now neva-<name>.timer`

Check: doctor shows the loaded count; each tool logs to `~/.local/state/neva/`.

## Disable / remove

macOS: `launchctl unload -w` alone is not reliable - a job can come back loaded (sometimes
with a live PID) even after both the plist AND the source install are deleted, because
`unload` can race a job that is mid-fire or about to fire on its own StartCalendarInterval.
The only removal that reliably stuck in testing (2026-08-01) is `bootout`, which tells launchd
to tear the job down immediately and unconditionally:

```
launchctl bootout gui/$(id -u)/com.neva.<name>
rm -f ~/Library/LaunchAgents/com.neva.<name>.plist
```

Confirm it is actually gone: `launchctl list | grep neva` should print nothing.

Linux: `systemctl --user disable --now neva-<name>.timer && rm -f ~/.config/systemd/user/neva-<name>.{service,timer} && systemctl --user daemon-reload`

## Testing this repo, not installing it

If you are running install.sh or build/verify.sh as a test/CI harness rather than a real
install, set `NEVA_SKIP_SCHEDULE_ENABLE=1`. Without it, `launchctl load` / `systemctl --user
enable --now` register against the REAL logged-in session regardless of what `$HOME` the test
overrides - a scratch sandbox does not sandbox the host scheduler. This is exactly how a ghost
`com.neva.cadence` ended up loaded (and had to be `bootout`) on a real dev machine from a test
run that never intended to touch it.

What each does: vault-sync moves agent writes between machines through git; canon-lint
checks people notes daily and messages you on real errors; cadence notices stale reviews or
journal and offers to draft; session-guard rotates the chat session before long-context
degradation makes the agent less accurate; lane-guard restarts the gateway if the Telegram
lane ever locks; vault-mirror keeps memory search fresh; diag runs the weekly self-test and
sends you the score.
