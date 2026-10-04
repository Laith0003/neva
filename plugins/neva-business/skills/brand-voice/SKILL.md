---
name: brand-voice
description: Use before writing anything public or outbound in a specific voice. Builds a source-derived VOICE PROFILE from real samples, stores it as the voice file every writing skill loads first, and bans generic AI tropes.
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Also draws on brand-profile (MIT, social skill set) and avoid-ai-writing (MIT, Conor Bronsdon) mechanics. -->

# Brand Voice

Build a durable voice profile from real source material, save it as the voice file, and load that file before any draft. Loading it after drafting is the failure mode: the draft is already shaped by defaults and the review turns into rewording instead of writing.

## When to Activate

- the user wants content or outreach in a specific voice
- writing for X, LinkedIn, Instagram, email, launch posts, threads, articles, site copy or product updates
- adapting one author's tone across channels or languages
- reviewing copy for AI tells or checking whether a draft sounds like the author
- a content lane needs a reusable style system instead of one-off mimicry

## The Voice File

One file per author or brand, owned by the user, stored where they choose (project repo, notes vault, or the Neva vault via `NEVA_VAULT`). Every writing skill (`content-engine`, `crosspost`, `article-writing`, `investor-outreach`, `lead-intelligence`, `email-ops`, `marketing-campaign`) reads it at step zero.

- Reuse the latest confirmed profile across related tasks in the session.
- Do not create repo-tracked files that store a person's voice fingerprint unless the user asks.
- If a `brand-system` document exists for the brand, its Voice section is the parent; this profile refines it and must not contradict it.

## Source Priority

Use the strongest real source set available, in this order:

1. recent original posts and threads by the author
2. articles, essays, memos, launch notes or newsletters
3. real outbound emails or DMs that worked
4. product docs, changelogs, README framing and site copy

Do not use generic platform exemplars as source material. Newer material beats older unless the user says the older writing is canonical. When the corpus and the user's explicit instructions disagree, the instructions win and the profile records the override.

## Collection Workflow

1. Gather 5 to 20 representative samples.
2. Separate public voice from private working voice if the set clearly splits.
3. Separate registers by surface (for example, sharp and opinionated in public posts, calm and restrained in client documents). Ask which surface a piece is for; never average two registers into one.
4. If live X access is available, use `x-api` to pull recent original posts.
5. For each language the author publishes in, record the variety and register per platform (for example, a spoken dialect on social, a light formal register in contracts). Content in that language is written in it, never translated from an English draft.
6. Record loanwords: when practitioners say the foreign term out loud, write it the way they say it instead of translating it into a textbook word.

## What to Extract

- rhythm and sentence length
- compression versus explanation
- capitalization norms
- parenthetical use
- question frequency and purpose
- how sharply claims are made
- how often numbers, mechanisms and receipts show up
- how transitions work
- proven sentence structures the author reuses (imperative, flat negation, story with a number)
- what the author never does

## Output Contract

Produce a `VOICE PROFILE` block using [references/voice-profile-schema.md](references/voice-profile-schema.md). Keep it short enough to load on every task. The point is operational reuse, not literary criticism.

Self-check before saving:

- a stranger could write an on-voice post from the profile without meeting the author
- lexicon is specific words, required and forbidden, not adjectives
- every banned move is observable in the sources or explicitly requested
- at least one point of view the voice stakes out, and one it rejects
- the profile is confirmed back to the user, with one round of edits offered

## Learning From Corrections

Every correction the user makes becomes a row in the profile's Accepted and Rejected log: the exact line, the verdict, and the reason in one clause, dated. Read the log before writing. A correction that was already logged and repeated is the most expensive mistake this skill can make.

## Default When Sources Are Thin

- direct, compressed, concrete
- specifics, mechanisms, receipts and numbers beat adjectives
- lead with the answer or the outcome; after one line the reader knows what the thing is
- confident, not persuasive
- parentheticals only for qualification
- conventional capitalization
- questions rare and never bait

## Hard Bans

Delete and rewrite any of these:

- em-dashes and double hyphens used as dashes
- emojis, unless the voice file explicitly allows them for a named surface
- fake curiosity hooks and bait questions
- "Excited to share", "In today's fast-paced world", "let's dive in", "it's worth noting"
- LinkedIn thought-leader cadence and generic founder-journey filler
- forced lowercase or all caps
- corny parentheticals
- rule-of-three flourishes that do no work

## Delete the Sentence, Do Not Reword It

The strongest AI tell is rhetorical shape, not vocabulary. Two shapes get the sentence deleted, not polished:

1. Antithesis, the "X, not Y" construction. One is survivable; several on a page read as generated.
2. Describing a virtue instead of stating a fact ("crafted with care", "built to last"). Replace it with the number, name or result, or delete it.

## Before Handing Anything Over

1. Read it aloud in your head. Would a normal person say this out loud? If not, cut it.
2. Search for em-dashes, `--` and emojis. Remove.
3. Cut the last sentence if it restates what was just said.
4. Every factual claim is checked against a source (see the fact-check gate in `content-engine`).
5. Optional mechanical pass for English: run the `avoid-ai-writing` detector if installed and fix every flagged span until it reports zero. It does not read other languages; those get the human read-aloud check against the profile.

## Downstream Use

Load this skill before or inside `content-engine`, `crosspost`, `article-writing`, `lead-intelligence`, `investor-outreach`, `email-ops`, `connections-optimizer` and `marketing-campaign`. If another skill carries a partial voice section, this profile is the source of truth.
