---
name: investor-outreach
description: Use when drafting cold emails, warm intro requests, follow-ups or updates to angels, VCs or accelerators. Personalized, one low-friction ask, drafted for review and never sent without explicit approval.
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Cold-email craft draws on coreyhaines31/marketingskills cold-email (MIT). -->

# Investor Outreach

Write investor communication that is short, concrete, and easy to act on.

## When to Activate

- writing a cold email to an investor
- drafting a warm intro request
- sending follow-ups after a meeting or no response
- writing investor updates during a process
- tailoring outreach based on fund thesis or partner fit

## Core Rules

1. Personalize every outbound message.
2. Keep the ask low-friction.
3. Use proof instead of adjectives.
4. Stay concise.
5. Never send copy that could go to any investor.

## Voice Handling

Load the voice file from `brand-voice` before drafting. If the user's voice matters and none exists, build it first.
This skill should keep the investor-specific structure and ask discipline, not recreate its own parallel voice system.

## Hard Bans

Delete and rewrite any of these:
- "I'd love to connect"
- "excited to share"
- generic thesis praise without a real tie-in
- vague founder adjectives
- begging language
- soft closing questions when a direct ask is clearer

## Craft Rules

- Write like a peer, not a vendor. Read it aloud; if it sounds like marketing copy, rewrite it.
- Every sentence earns its place. The best cold emails feel like they could have been shorter.
- The personalization must connect to the ask. If you can delete the personalized opening and the email still makes sense, it is not working.
- Lead with their world: "you" outweighs "I" and "we". Do not open with who you are.
- One low-friction ask. An interest question beats a request for a 30-minute call on first touch.
- Subject lines: short, plain, internal-looking. No tricks, no fake "Re:", no urgency.
- Plain text, at most one link, no images.
- Quality check before presenting: would you reply to this? Is the proof concrete? Is there exactly one ask?

## Cold Email Structure

1. subject line: short and specific
2. opener: why this investor specifically
3. pitch: what the company does, why now, and what proof matters
4. ask: one concrete next step
5. sign-off: name, role, and one credibility anchor if needed

## Personalization Sources

Reference one or more of:
- relevant portfolio companies
- a public thesis, talk, post, or article
- a mutual connection
- a clear market or product fit with the investor's focus

If that context is missing, state that the draft still needs personalization instead of pretending it is finished.

## Follow-Up Cadence

Default:
- day 0: initial outbound
- day 4 or 5: short follow-up with one new data point
- day 10 to 12: final follow-up with a clean close

Do not keep nudging after that unless the user wants a longer sequence.

## Warm Intro Requests

Make life easy for the connector:
- explain why the intro is a fit
- include a forwardable blurb
- keep the forwardable blurb under 100 words

## Post-Meeting Updates

Include:
- the specific thing discussed
- the answer or update promised
- one new proof point if available
- the next step

## Send Gate

This skill drafts. Sending goes through `email-ops` (or the relevant channel skill) and waits for an explicit yes on the exact final message, recipient and sender account. Each follow-up in a cadence is its own approval; a scheduled sequence is approved as a whole only after every message in it has been shown.

## Quality Gate

Before delivering:
- the message is genuinely personalized
- the ask is explicit
- the proof point is concrete
- filler praise and softener language are gone
- word count stays tight
