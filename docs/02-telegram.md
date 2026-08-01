# Telegram: your agent in your pocket

Do this only after first-run success in the terminal.

## Create the bot (2 minutes)
1. In Telegram, open a chat with @BotFather. Confirm the handle is EXACTLY @BotFather.
2. Send `/newbot`. Follow the two prompts (a display name, then a username ending in `bot`).
3. BotFather replies with a token like `1234567890:AA...`. Treat it like a password.

## Wire it, locked down from the first minute
1. Put the token in `~/.openclaw/openclaw.json` under `channels.telegram.botToken`.
   Never commit this file anywhere.
2. Get your numeric id: message @userinfobot, it replies with your id.
3. Set BOTH `channels.telegram.dmPolicy: "allowlist"` AND
   `channels.telegram.allowFrom: [<your numeric id>]`. THIS IS NOT OPTIONAL: without the
   allowlist policy the default is `pairing`, which is weaker than locking the bot to you.
4. Restart the gateway. Message your bot. It should reply, and doctor should show
   `telegram token (getMe 200)` and `telegram allowFrom locked`.

## Errors, by exact message
| You see | It means | Fix |
|---|---|---|
| getMe returned 401 | token wrong or revoked | regenerate with BotFather, update the config |
| bot never replies but doctor is green | gateway not restarted after config change | stop and restart: `openclaw gateway` |
| replies to a friend who found the bot | allowFrom not set | set it now, step 3 above |
| duplicate replies on long questions | polling watchdog shorter than slow turns | raise `channels.telegram.pollingStallThresholdMs` in ~/.openclaw/openclaw.json; see docs/10-configuration.md and docs/07-troubleshooting.md |

More errors and solutions: [docs/07-troubleshooting.md](07-troubleshooting.md)
