# Integrations

This page says what actually runs, not what would be nice. Every line below was verified
against the code on 2026-08-01: installed a real hledger, ran a real Open Food Facts lookup,
grepped every tool for the config keys it claims to use. Two things that used to be listed
here were cut because nothing in the product calls them; see "Cut" at the bottom, and why.

## Ships enabled

- **hledger**: money journal in `05 Money/*.journal` (one file per year is fine; the agent
  reads all of them). Single command install: `brew install hledger` (macOS and Linux) or
  `apt install hledger` (Debian/Ubuntu). Verified live: append a transaction with a text
  editor, then `hledger balance` reflects it immediately, no reindex step.
  Source: https://hledger.org/install.html

  Two tools read it:
  - `canon` (fixed 2026-08-01): any money-shaped question runs `hledger balance` fresh, at
    query time, against every `05 Money/*.journal` file found, and shows the real command
    output. It no longer trusts a cached figure - see "What changed" below.
  - `money`: a direct CLI for balance/register/print queries and for `money check`, which
    scans the rest of the vault for currency-shaped text living outside `05 Money/` (a
    second money file is how a figure the agent can't ground gets born).

  Output format: hledger's own JSON (`-O json`) nests every amount as
  `{decimalMantissa, decimalPlaces, floatingPoint}` rather than a plain number, and
  `register --output-format json` is a bare array with no field names
  (https://github.com/simonmichael/hledger/issues/2552, "difficult to consume"). Both tools
  use `-O csv` instead, which prints a flat `"1000.00 USD"` string per line - what an LLM
  should actually parse. Tested both formats against a real journal before choosing.

- **Telegram**: the only push channel this product ships. Every guard, nudge, and alert
  (`alert`, `cadence`, `session-guard`, `lane-guard`, `vault-sync`, `canon-propose`,
  `briefing`) sends through the same bot, to `OWNER_CHAT_ID`. See "Cut: ntfy" below for why
  there isn't a second channel.

- **git-based vault sync** ("the git brain"): `vault-sync` (node/VPS side) and
  `vault-sync-companion` (Mac side) keep the vault in sync by committing and pushing/pulling
  a bare git repo between machines, with a canon-gate hook and quarantine-on-rejection
  recovery. This is what actually keeps your vault on two machines - see "Cut: syncthing
  and obsidian-git" below for what it replaced.

- **Dataview + heatmap** (Obsidian plugins, install inside Obsidian): dashboards over
  agent-written fields, view-only, no risk of double-writing.

- **Open Food Facts** (`food-lookup`, new 2026-08-01): keyless barcode and name lookup.
  Required: a custom `User-Agent` on every call (OFF's own terms) and a hard timeout, since
  a hung lookup is worse than no lookup. Rate limits, confirmed against OFF's current API
  docs: 15 req/min/IP for product reads, 10 req/min/IP for search
  (https://openfoodfacts.github.io/openfoodfacts-server/api/). `food-lookup` sets the
  User-Agent and a 10s `--max-time` on every call; it does not rate-limit you across
  separate invocations, so do not loop it in a tight shell for-loop.
  Tested live: a real barcode (Nutella, 3017620422003) returns name/kcal/protein; a
  nonexistent barcode returns "not found" and refuses to guess a value; killing the network
  produces a fast, clear failure, not a hang.
  `bin/food` (the daily log/macro tracker) does **not** call `food-lookup` automatically -
  that would require editing `bin/food`, an existing tool outside this change's scope. Until
  someone wires it in, `food-lookup` is a companion the agent shells out to by hand when
  given a barcode, then pastes the result into `food log`.

Documented, install when wanted: taskwarrior/timewarrior, beancount + fava, Actual Budget,
jrnl, himalaya (email), khal (CalDAV), Miniflux (RSS), atuin, yt-dlp/ffmpeg/pandoc.
Note on the Tasks plugin: its default emoji signifiers conflict with the no-emoji house
style; use its dataview-field mode.

Nutrition otherwise has no good open-source self-hosted answer, so the vault ships a
markdown-adjacent (JSON) food log the agent parses (see `Food/`), with `food-lookup` above
for packaged items with a barcode.

**Not compatible, corrected 2026-08-01**: the previous version of this page said the food
log was "compatible with the Obsidian Macros plugin." It is not. Macros ingests data two
ways: a `​```macros` codeblock referencing a food-database file, or its own UI search against
FatSecret/USDA/Open Food Facts. `bin/food` writes one plain JSON file per day; nothing
translates that into a Macros codeblock or food-database file, and Macros' own docs give no
guidance for external tools generating compatible entries. If you want Macros' dashboards,
use its own food search inside Obsidian; it will not see what `bin/food` logs, and
`bin/food`'s log will not see what Macros logs. Two separate logs, not one.

## What changed in `canon` (2026-08-01), and why it matters here

`canon`'s money lookup used to read a `<!-- MONEY-ANCHOR-START -->...<!-- MONEY-ANCHOR-END
-->` block out of a workspace file (`TOOLS.md`) that nothing in this codebase ever wrote.
Verified before the fix: a fresh install, asked `canon "balance"`, returned nothing for
money at all - the read path existed, the write path never did, and it failed silently.
This is very likely the shape of bug behind the live finding that the founder's own system
quoted an after-tax figure that existed in no file: a promised, "automatic" cache that
nothing kept honest. `canon` now runs `hledger balance` live, at query time, against the
real `05 Money/*.journal` files and says so in the output; a legacy cached block, if one
ever exists, is now shown last and explicitly labeled "UNVERIFIED CACHED NOTE... prefer the
live block above if the two disagree." If hledger is not installed, `canon` shows the raw
journal text verbatim and tells the model not to do the arithmetic itself, rather than
inventing a parser that could get multi-currency or elided amounts subtly wrong.

Nothing above the promise changed: "money figures come only from the ledger file" (see
`vault/CLAUDE.md`, `workspace/AGENTS.base.md`). What changed is that the promise is now
backed by code that runs on every query instead of a cache that was never populated.

## Cut: ntfy

Cut, not built. `docs/08-integrations.md` used to describe ntfy as "the product's second
channel, the push nervous system for guards and timers" and told you to set `NTFY_TOPIC` in
identity.env. Verified 2026-08-01 by grepping every tool in `bin/`, `lib/`, and `services/`
for `NTFY` and `ntfy`: zero matches outside this doc. `NTFY_TOPIC` exists as a config key in
`identity.env.example` and is written by `install.sh`, but nothing ever reads it. A buyer
who followed the old docs and set the topic got permanent, silent, unexplained silence -
worse than the feature simply not existing, because there was no error to tell them so.

Why cut rather than build:
- Every guard and nudge this product ships (`alert`, `cadence`, `session-guard`,
  `lane-guard`, `vault-sync`, `canon-propose`, `briefing`) already sends through Telegram,
  fully configured during setup. ntfy was pitched to cover exactly the use case Telegram
  already covers; it would be a second channel for zero new coverage.
- ntfy.sh's own terms make the topic name the entire access control: "you are responsible
  for choosing topic names that cannot be easily guessed... ntfy is not responsible for any
  unauthorized access to messages published to easily guessable topic names"
  (https://docs.ntfy.sh/terms/). For a buyer who is "semi-technical, not an r/selfhosted
  engineer" (this product's stated persona), a leaked or guessed topic is a silent, public
  read/write channel into their guard and cadence notifications - a worse failure mode than
  "no second channel."
- Tested it anyway before ruling it out: a keyless `curl -d "..." https://ntfy.sh/<topic>`
  publish is real, free, and fast (measured: HTTP 200 in ~0.5s, no signup). Rate limit,
  confirmed against the project's own tracker discussion: 60-request burst then 1 request
  per 10 seconds by default (https://github.com/binwiederhier/ntfy/issues/1173,
  https://docs.ntfy.sh/faq/). The mechanics are fine. The gap is that wiring it in for real
  means touching seven existing tools this change is not scoped to modify, to add a second,
  independently-configured notification path next to one that already works.

If a future buyer genuinely wants a channel independent of Telegram (e.g. Telegram is
blocked in their country), the honest fix is a shared `lib/notify.sh` helper that both
Telegram and ntfy call through - not a second hand-rolled `curl` block. Which points at the
next problem:

**Also found, not this change's to fix**: the Telegram send itself is duplicated seven
times (`alert`, `canon-propose`, `cadence`, `vault-sync`, `briefing`, `session-guard`,
`lane-guard`), each with its own copy of "read the bot token out of openclaw.json, curl
sendMessage." One shared `lib/notify.sh` would remove six copies of that logic and would
also be the right place to add ntfy later if the case for it ever changes. Flagging for
whoever owns those files; not touched here.

## Cut: syncthing (as documented)

The old line here read "syncthing: vault on your phone and laptop. Single binary." Verified
2026-08-01: `syncthing` does not appear anywhere in `bin/`, `lib/`, `services/`, or
`install.sh` - only in this doc. `install.sh` never installs it, no service template renders
a syncthing config, and no tool shells out to it. What the product actually ships for
multi-machine sync is `vault-sync` + `vault-sync-companion`, a bidirectional git sync with a
canon-gate hook and a quarantine-and-notify recovery path for rejected pushes (see the
comments in both files). That mechanism is real, tested by the founder's own live system,
and already does what syncthing was pitched for.

Do not additionally install Syncthing (or the obsidian-git plugin, also previously listed
here) on top of the git-based sync this product already runs. Two independent, automated
writers committing/syncing the same working directory is a documented source of corruption
in real reports: Syncthing users have reported "dozens of .sync-conflicts" from a single
known bug even with Syncthing alone on an Obsidian vault
(https://forum.syncthing.net/t/obsidian-conflicts/19101), and the general advice across the
Obsidian-sync ecosystem is not to run a file-sync tool and a git-based sync tool against the
same vault at once, because both mutate the working tree on their own timers and can race
each other or produce spurious commits/conflicts neither expects. The git-brain sync this
product ships already solves the "vault on two machines" problem; adding a second syncer is
pure downside.

If you want the vault ALSO on your phone read-only, that is a different, lower-risk problem
(one reader, no writer) and is not addressed by this page yet.
