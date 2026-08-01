# Voice: customize your agent's personality

Your agent's personality is configured in `SOUL.local.md`, in your workspace. It was written
once, during your first conversation, from how you typed: the sentence length, punctuation,
formality, what you care about. This document covers how to customize it after setup.

## What SOUL.local.md controls

Open `~/.openclaw/workspace/SOUL.local.md` (or your configured `WORKSPACE_PATH`/SOUL.local.md).
It has four sections:

- **Agent name:** what you call your assistant day to day.
- **Voice:** observations of how you write (length, tone, language). The agent reads this
  every conversation and tries to match it. Edit this if the agent sounds wrong.
- **Proactivity:** when the agent may message you first, and what kinds of messages annoy you.
  The "annoyance line" from your interview is the most important sentence here.
- **Boundaries:** your actual working hours, communication preferences, and anything else that
  should shape when and how the agent reaches you.

The agent re-reads SOUL.local.md at the start of every conversation; changes take effect
immediately.

## Voice: how to fix a mismatch

If the agent sounds too formal, too casual, too chatty, or not like you, edit the Voice
section of SOUL.local.md. Be specific and concrete.

Examples of good edits:

- If the agent is too formal: "Short, direct sentences. Contractions. No 'indeed' or 'whilst'.
  One-liner sarcasm is fine."
- If the agent is too chatty: "Cut the pleasantries. Lead with the answer. No reactions to
  small answers."
- If the agent mixes languages wrong: "English primary, Arabic when naming money or people.
  No French."

Examples of edits that do NOT work:

- "Be funnier." (Not actionable; the agent cannot infer funny from abstraction.)
- "Sound like Steve Jobs." (Not concrete; the agent has no way to know who that is.)
- "Be yourself." (The agent has no self; it is a reflection. Write what YOUR voice is
  instead.)

After you edit SOUL.local.md, say something conversational to the agent (not a directive;
just talk to it like normal). It will see the new voice description and adjust. If the
adjustment is still off, repeat the edit. It usually takes 2-3 rounds to land on something
that feels right.

## Proactivity: when the agent may reach you first

The Proactivity section controls whether the agent sends you unsolicited messages (drafting
a review, warning you of a deadline, reminding you to eat). By default, proactivity is OFF.

To enable it, edit the relevant line in SOUL.local.md:
- "reviews": if on, cadence will draft a weekly review and message you when it is ready.
- "reminders": if on, lane-guard and other jobs will send you alerts about things that need
  attention.
- "checkins": if on, the agent will ask you about progress on active projects (Day 2+, per
  docs/03-scheduled-jobs.md).

Each is a yes/no flag. Set it to "yes" to enable, "no" to disable.

If you enable any proactivity, the agent will also read your ACTIVE_HOURS_* settings from
`~/.config/neva/identity.env`. Messages are never sent outside those hours (adjusting for
timezone).

## Annoyance line: the most important sentence

During your first conversation, you answered: "what kind of unsolicited message would annoy
you?" Your exact answer is in the Proactivity section, quoted verbatim. That sentence is the
agent's north star for when to stay quiet.

Example: "If I am in the middle of something, don't interrupt. Message me when I usually
check chat, not in the middle of my workday."

The agent re-reads that before every proactive message and asks itself: "would this annoy
them?" If the answer is yes, it holds the message. This is not a hard rule; the agent can
get it wrong. But it is what shapes every proactive decision.

If your annoyance line no longer matches how you feel, edit it. Keep it short and specific.

## Tone: what SOUL.local.md does NOT control

SOUL.local.md is about voice and proactivity. It does not control:

- **What the agent knows.** Vault content (notes in ~/Vault) is the agent's only source of
  truth about your life. SOUL.local.md cannot add knowledge.
- **What the agent can do.** Its capabilities are set in the OpenClaw agent definition
  (workspace/AGENTS.base.md). SOUL.local.md cannot unlock new tools.
- **Whether the agent can actually reach you.** Telegram must be set up first (docs/02-telegram.md)
  and the allowlist must be locked (docs/09-security.md). SOUL.local.md cannot fix a broken
  channel.

If the agent's behavior is wrong in ways that are not about voice or proactivity, it is
almost always a vault problem (missing notes), a configuration problem (missing identity.env
keys), or a setup problem (Telegram not configured). Use `doctor` first; every FAIL or WARN
it shows points to what to fix.

## Example: a complete voice customization

You set up Neva. The agent sounds stiff. You open SOUL.local.md and see:

```
## Voice
From how you've typed here: medium-length messages, conversational, some punctuation quirks.
You use Arabic for money and people-names. You joke occasionally.
```

This is OK but not quite you. You edit it to:

```
## Voice
Short, direct sentences. Arabic for money/people. Lead with the answer. Use contractions.
One-liners are fine. Skip reactions to one-word answers.
```

Next message to the agent, it sees the new voice section and adjusts. If it overshoots and
becomes too terse, you refine: "Conversational, but terse. Contractions, no 'by the way',
short reactions." Another round, you land on it.

Now, the agent sounds like you. It stays that way until you edit SOUL.local.md again.

## Resetting voice to defaults

If you want to start over, delete the Voice section of SOUL.local.md entirely. On the next
conversation, the agent will re-read it, find it missing, and revert to the floor in
SOUL.base.md (short sentences, direct, no emojis, one question at a time). From there you
can build the voice up again.

Do not edit SOUL.base.md itself; it is part of the product and gets overwritten on updates.
All your customizations live in SOUL.local.md.
