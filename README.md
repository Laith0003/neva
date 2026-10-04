# Neva

**An assistant that never makes things up.**

Your own AI on Telegram, running on your machine, with a memory you can open in Obsidian.
It answers questions about your world from YOUR notes, cites the file it read, and says
"I don't have that" when the note doesn't exist. It watches its own health, rotates its own
sessions before long-context drift makes it sloppy, and messages you when something needs a
human.

> **Two ways to run this.** The simple one needs only Claude Code and Obsidian: it already has a
> model and already reads this folder, so nothing installs and nothing can be misconfigured. The
> upgrade adds openclaw so the same assistant answers on Telegram while your laptop is shut. Start
> simple; the upgrade is there when you want it.
>
> **Early, and testers are the point.** `build/verify.sh` installs it from scratch in a stripped
> sandbox and asserts the outcomes you would actually notice, and each check is proven able to
> fail. It passes on macOS, and on Linux in CI on every push; no person has yet reported a real
> Linux install, so on Linux you are among the first. Read [docs/00-testing-this.md](docs/00-testing-this.md) before
> you spend an hour, and tell us what broke: that is worth more to this project right now than
> a star.

Most self-hosted assistants die two deaths: they hallucinate about your life, or they rot
(sessions bloat, syncs wedge silently, gateways end up exposed). This template exists
because both are preventable with structure, not with hope.

Every claim below is asserted by `build/verify.sh`, which installs the product from scratch
in a stripped-down sandbox that deliberately withholds the optional dependencies, then checks
the outcome a buyer would care about rather than an exit code. Every check is also proven able
to fail. If a promise here stops being true, that harness goes red before you ever see it.

## What you get

- **Grounded answers.** People, clients, money, dates: asserted only from vault notes, with
  the source named. Money is read live from your ledger on every question, never from a
  cached total, so a figure it cannot find in the ledger is one it tells you it cannot find.
- **A real setup interview.** Your agent's first conversation configures it. If an AI reads
  START.md, that agent runs the interview. If you install manually, your assistant runs the
  same interview itself the first time you talk to it. Either way it is one interview, six
  questions, once. It is never run twice.
  Either way, the agent learns your writing voice from how you type, not from asking.
- **Guards that watch the assistant itself.** Scheduled checks catch session bloat, locked
  channels, and wedged syncs. Some repair themselves; the rest tell you what broke and what
  to run. You turn them on during setup, one at a time, and `doctor` shows which are live.
- **Closed by default.** Loopback-only gateway, Telegram locked to your id, tokens never in
  tracked files. `doctor` fails loudly on the two mistakes that get self-hosters burned.
- **A vault that is yours.** Plain markdown in Obsidian. One person one note, enforced.
  hledger for money, and a food log the agent can total.
- **A disciplined coding harness (new in 0.10).** A Claude Code plugin marketplace: one process
  loop (research, plan with a confirm gate, tests first, implement, review from a fresh context,
  verify with evidence, remember, improve), reviewers and planners that run in their own
  context, and a Python hook runtime that enforces what reminders cannot. It learns: tool use
  is observed, a nightly job distils lessons into notes in your vault, and nothing becomes
  durable memory until you approve it. See [The coding harness](#the-coding-harness).

## Start here

**[SETUP GUIDE.md](SETUP%20GUIDE.md)** walks you through it in five steps, prerequisites first.
The short version:

## Quick start: say "start"

**For AI agents:** Open this folder and say **start**. The agent reads START.md, interviews you
with six questions about your work, what you want off your plate, and how you like to be spoken to,
then silently builds the whole system behind your answers. Your goals, projects, and
personality all come from that one conversation. It ends by doing a real task for you.

**For manual setup:** Follow these four steps.
1. Install [Claude Code](https://claude.com/claude-code) and [Obsidian](https://obsidian.md)
   (add [openclaw](https://docs.openclaw.ai/install) only for the always-on Telegram upgrade)
2. `./install.sh` and answer three identity questions
3. Fix anything `doctor` marks FAIL (each row names its fix)
4. Talk to your agent in the terminal; its first conversation is the interview
Then, and only then: [docs/02-telegram.md](docs/02-telegram.md)

**macOS: proven.** Tested end to end in a real install (see `build/verify.sh`).
**Linux: the harness passes, real installs unreported.** `build/verify.sh` passes on Linux in
CI on every push and passed on a Linux machine on 2026-08-14 after two GNU-vs-BSD fixes. No
person has reported a real Linux install yet. Read [docs/00-testing-this.md](docs/00-testing-this.md)
before you start, and report what breaks.
**Windows:** WSL2 only, and inherits the Linux caveat above (WSL2 is Linux).

## The coding harness

Neva ships a Claude Code plugin marketplace in this repo. Add it once, then install what you use:

```
claude plugin marketplace add /path/to/neva
claude plugin install neva-core@neva
```

| Plugin | What it holds |
|---|---|
| `neva-core` | The process loop, planner, architect, code and security reviewers, TDD guide, the learning engine (instincts), session memory, compaction discipline, orchestration, the Python hook runtime |
| `neva-web` | PHP and Laravel, TypeScript, React, Next, Vue, Nuxt, Angular, databases, frontend patterns |
| `neva-mobile` | Flutter and Dart, Swift and SwiftUI, Kotlin and Compose, React Native |
| `neva-backend-langs` | Python, Django, FastAPI, Go, Rust, Java, Spring, Quarkus, Kotlin server, C++, C#, F#, Perl, Rails |
| `neva-ops` | Docker, Kubernetes, deployment with a production gate, homelab, networking |
| `neva-business` | Research, content, investor materials, social publishing; every outbound action stops for your yes |
| `neva-media` | Video, motion, document processing |
| `neva-domains` | Healthcare, supply chain, machine learning, scientific and market domains |

Keep `neva-core` on everywhere and enable the others per project, so the skill list stays small.
Hook profiles: `NEVA_HOOK_PROFILE=minimal|standard|strict`; switch any module off with
`NEVA_DISABLED_HOOKS`. Details: [docs/harness/](docs/harness/).

Much of the harness is adapted from Affaan Mustafa's
[Everything Claude Code](https://github.com/affaan-m/ECC) (MIT), merged with Neva's brain and
rewritten to run on Python's standard library. See [NOTICE](NOTICE).

## The honest part

This connects an LLM to your notes and your Telegram. Read
[docs/09-security.md](docs/09-security.md) before exposing anything to the internet; it says
plainly what the defaults protect against and what they cannot.

## Licence

[Functional Source License 1.1](LICENSE.md), with Apache-2.0 as the future licence.

Use it, change it, run it for yourself or inside your company, free, forever. Fork it and
publish your fork. The single restriction: you may not sell it, or sell a product that
substitutes for it, without a separate agreement. Two years after each version is published,
that version becomes Apache-2.0 and the restriction lifts on it entirely.

The name is separate: the licence covers the code, not the word "Neva". See
[TRADEMARK.md](TRADEMARK.md). A fork may do anything except present itself as this one.

Contributions welcome, including ones that change how this works. Sign commits with
`git commit -s`; that one line is the whole legal process. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Who built this

Neva is by [Laith Aljunaidy](https://laithjunaidy.com), built first as his own assistant and
only later as something to hand over. Background, why it exists, and how to get in touch:
[AUTHOR.md](AUTHOR.md).
