---
name: content-engine
description: Use when producing social posts, threads, scripts, newsletters or a content calendar, or adapting one source asset across platforms. Source first, voice file first, fact-check gate, hook ranking, human picks.
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Also draws on coreyhaines31/marketingskills social-content and content-strategy (MIT) for planning mechanics. -->

# Content Engine

Build platform-native content without flattening the author's real voice into platform slop, and without shipping a claim nobody checked.

## When to Activate

- writing X posts or threads, LinkedIn posts, Instagram carousels or captions
- scripting short-form video or YouTube explainers
- repurposing articles, podcasts, demos, docs, books or internal notes into public content
- building a launch sequence, a weekly batch, or an ongoing content system
- deciding which of several drafted pieces to make next

## Non-Negotiables

1. Load the voice file before drafting (`brand-voice`), and the brand document if one exists (`brand-system`). Never after.
2. Start from source material, not generic post formulas.
3. One piece carries one claim or one story. If it needs two lessons to be interesting, it is two pieces.
4. Specificity beats adjectives.
5. Every date, number, name and quote passes the fact-check gate before production starts.
6. No engagement bait unless the user explicitly asks for it.
7. This skill never publishes. Finished pieces go to `social-publisher`, which runs the publish gate and stops for an explicit yes.

## Step 0: Context

Read, in order: the voice file, the brand document, the content tracker (what was already published, what performed, what is queued), and any brief handed over. If the tracker shows the same angle shipped recently, say so before drafting.

## Step 1: Mine the Source Into Units

A unit is one piece of content. It has a person, a time, a problem and a turn. A fact, a tip or a principle is not a unit.

1. Read the whole source first. Do not mine as you read; the best units are often assembled from material split across sections.
2. Find the turn: the one sentence where the story stops being a story and becomes a point. No turn, no unit.
3. Keep the story and the point in separate fields. The piece opens inside the story with the point nowhere in sight.
4. Write the modern parallel: where this shows up today. If nothing comes, the unit is weaker than it looks.
5. Grade strictly: A carries a piece alone, B needs pairing or is short, C is supporting detail only. Forty A units beat two hundred mixed ones.
6. Flag verification on sight: round ancient dates, famous quotes attached to famous demonstrations, a company credited for one person's invention, before-and-after numbers reported by the person selling the method, any anecdote with a perfect ending and vivid detail no source carries. Set `verified: pending`.

## Step 2: Fact-Check Gate

Runs before a unit moves into production, never after. A checked script costs an hour; a wrong published claim costs the position.

Verdicts, and only these three:

| Verdict | Meaning | Action |
| --- | --- | --- |
| pass | every claim traced to a credible source | ships |
| fix | the core holds, a detail is wrong | correct the detail, note it in the unit, ship |
| fail | the claim cannot be attributed or contradicts the record | does not ship; rewrite around what is documented, or drop |

Never soften a failed claim into "some say" or "the story goes". That is how a wrong fact ships wearing a hedge.

Check in order: attribution (a named person, not "researchers"), date (wrong by a decade is a fail), every number (find the original and who counted it), the quote (default to cutting it and keeping the event), the competing version (two incompatible versions means the anecdote grew).

Source ranking: primary records first, then specialist literature and cited reference works, then blogs and posts (three blogs agreeing is one source), and never a model's recollection, including yours. If every hit traces back to the same retelling, the claim is unverified.

The failure signature: vivid detail no source carries, several incompatible versions, a perfect ending, citations that only lead to other retellings. Seeing it is a fail even without disproof; the burden is on the claim. The documented version is usually the better story. Treat a fail as the piece you were actually going to make.

## Step 3: Hooks

Generate at least five openings per unit, then rank on:

1. Time to question: seconds before the reader or viewer has a question. Short-form video needs it in the first few seconds.
2. Share test: would someone send this to a specific person? Reversed assumptions, a physical object at the end of a story, and a number that sounds wrong get forwarded. Tips, lists and homework get saved and forgotten; route those to carousels or threads instead of video.
3. Truth: does it survive the fact-check gate? A hook that overstates is a fail, not a stretch.
4. Voice: does it match the voice file?

Dead on arrival: "did you know", naming the lesson, promising value later, a question the audience can answer with no, any preamble. Output the top three with the reason for each. The human picks.

## Step 4: Platform Adaptation

### X
- open with the strongest claim, artifact or tension
- keep the compression if the source voice is compressed
- a thread only when one post would collapse the argument; each post advances it

### LinkedIn
- open with the insight or a point of view, never an announcement
- expand only enough for people outside the niche to follow
- no corporate inspiration cadence, no praise-stacking, no closing question to farm replies

### Instagram and carousels
- the cover carries the hook alone; each slide earns the swipe
- headlines read as one paragraph when listed in order; if the list does not tell the story, the deck does not either
- alt text written in the platform's language

### Short video
- script around the visual sequence and proof points
- first seconds show the result, problem or punch
- do not write narration that sounds better on paper than on screen

### YouTube
- show the result or tension early; organize by argument, not filler sections

### Newsletter
- open with the point, conflict or artifact; every section adds something new

## Repurposing Flow

1. Pick the anchor asset.
2. Extract 3 to 7 atomic claims or units.
3. Rank by sharpness, novelty and proof.
4. Assign one strong idea per output.
5. Adapt structure per platform.
6. Strip platform-shaped filler.
7. Run the quality gate.

## Review File

Each piece gets one review file next to it. Scripted gate output (detector runs, legibility checks, fact-check verdicts) is pasted verbatim, never paraphrased. Prose gates get a real answer and a `VERDICT:` line. When an asset is rebuilt, the gates that described the old one are stale: rerun them, do not carry the old verdict forward.

A gate that passes is not a verdict. The last gate is the eye: open the final rendered asset (the image, the video frame, the formatted post) and look at it before the human sees it. Scripted gates regularly pass work a person rejects in one glance.

## When the User Corrects You

Corrections usually arrive in one line and are usually right about something the gates cannot see. Apply the fix, add the rule to the voice file log or this piece's review file, and do not argue the target back.

## Measurement Loop

- Read metrics, never write them. Pull numbers at fixed windows after publishing (24 hours and 7 days by default). Platform day boundaries and data finality lag vary; mark provisional numbers as provisional, never as zero.
- Grade each post against the account's own measured bands (its quartiles for reach, saves, shares, follows), not generic industry benchmarks.
- One action per report: repeat, stop, or change one thing.
- Keep the user's goal on the report as stated, and put the measured pace and the honest forecast beside it. The goal never rewrites the gates.
- Feed results back into the hook ranking rules. When the account's baselines move, the rules move with them; do not keep quoting stale numbers.
- Record every published piece in the content tracker with its permalink so the measurement pass can attach numbers.

## Deliverables

For a campaign or batch, return:

- the voice profile in use (or a note that none exists yet)
- the core angle and the units, graded, with verification status
- ranked hooks, top three per unit
- platform-native drafts
- posting order only if it helps execution
- gaps to fill before publishing

## Quality Gate

Before delivering:

- every draft sounds like the intended author, not the platform stereotype
- every draft contains a real claim, proof point or concrete observation
- every date, number, name and quote carries a pass or an applied fix
- no hype language, no fake engagement bait, no em-dashes, no emojis unless the voice file allows them
- no duplicated copy across platforms unless requested
- any CTA is earned and user-approved
- the rendered asset was looked at, not only the text

## Related Skills

- `brand-voice` for the voice file, loaded first
- `brand-system` for the brand document
- `crosspost` for platform-specific distribution
- `social-publisher` for the publish gate and delivery
- `x-api` for sourcing recent posts and approved X output
- `article-writing` for long-form pieces
