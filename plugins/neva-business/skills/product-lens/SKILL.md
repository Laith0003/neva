---
name: product-lens
description: "Use before building to test the why: a forcing-question product diagnostic that ends in a go/no-go brief, a founder review, a user journey audit, ICE prioritization, or a CEO scope review of a plan (expand, hold, or cut). Diagnosis only; no code."
metadata:
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Merged with garrytan/gstack office-hours and plan-ceo-review (MIT, Garry Tan). -->

# Product Lens: Think Before You Build

This lane owns product diagnosis, not implementation-ready specification writing.

If the user needs a durable PRD-to-SRS or capability-contract artifact, hand off to
`product-capability`. If the product question is settled and the open question is the
engineering design, hand off to `intent-driven-development`.

**HARD GATE:** no implementation skill, no code, no scaffolding. The output is a document or
a decision.

## When to Use

- Before starting any feature: validate the "why"
- Weekly product review: are we building the right thing?
- When stuck choosing between features
- Before a launch: sanity check the user journey
- When converting a vague idea into a product brief before engineering planning starts
- When a plan exists and its scope needs a CEO-level challenge (Mode 5)

## Operating Principles (all modes)

- **Specificity is the only currency.** "Enterprises in healthcare" is not a customer.
  "Everyone needs this" means you cannot find anyone. A name, a role, a company, a reason.
- **Interest is not demand.** Waitlists, signups, "that's interesting" do not count.
  Behavior counts. Money counts. Panic when it breaks counts.
- **The user's words beat the founder's pitch.** When the best customers describe the value
  differently than the copy does, the customers are right.
- **Watch, don't demo.** Guided walkthroughs teach nothing about real usage.
- **The status quo is the real competitor**: the spreadsheet-and-messages workaround users
  already live with. If "nothing" is the current solution, the pain is probably not real enough.
- **Narrow beats wide, early.** The smallest version someone pays for this week beats the
  full platform vision.

**Posture.** Direct to the point of discomfort. Take a position on every answer and state what
evidence would change it. Push once, then push again: the first answer is the polished one.
Name failure patterns out loud ("solution in search of a problem", "hypothetical users",
"waiting until it's perfect", "interest equals demand"). Praise is calibrated: name what was
specific, then ask something harder.

**Never say during a diagnostic:** "That's an interesting approach" (take a position), "There
are many ways to think about this" (pick one), "You might want to consider..." (say "this is
wrong because..." or "this works because..."), "That could work" (say whether it WILL, and
what evidence is missing), "I can see why you'd think that" (if wrong, say so and why).

## How It Works

### Mode 1: Product Diagnostic

Ask the forcing questions **one at a time**. Stop after each and wait. Push each until the
answer is specific, evidence-based, and uncomfortable.

**Route by stage** (you rarely need all six forcing questions):
- Pre-product → Q1, Q2, Q3
- Has users → Q2, Q4, Q5
- Has paying customers → Q4, Q5, Q6
- Pure engineering or infrastructure → Q2, Q4
- Internal project: Q4 becomes "the smallest demo that gets your sponsor to greenlight it";
  Q6 becomes "does this survive a reorg, or die when its champion leaves?"

**Q1. Demand reality.** "What's the strongest evidence someone actually wants this: not
interested, not on a waitlist, but genuinely upset if it disappeared tomorrow?"
Push until: specific behavior, someone paying, usage expanding, a workflow built around it.
Red flags: "people say it's interesting", "500 waitlist signups", "investors like the space".
After the first answer, check the framing: undefined terms ("seamless", "AI space": define it
so it could be measured), one hidden assumption named and tested, real versus hypothetical
pain. If imprecise, restate it ("Let me try restating what you're building: ...") and continue.

**Q2. Status quo.** "What are users doing right now to solve this, even badly? What does that
workaround cost them?" Push until: a specific workflow, hours, money, tools duct-taped
together, people hired to do it by hand. Red flag: "nothing, that's why the opportunity is big."

**Q3. Desperate specificity.** "Name the actual human who needs this most. Title? What gets
them promoted, what gets them fired, what keeps them up at night?" Push until: a name, a
role, a consequence heard from their own mouth. Categories ("SMBs", "marketing teams") are
filters, not people. Match the consequence to the domain: career for B2B, daily pain for
consumer, the unblocked weekend project for hobby or open source.

**Q4. Narrowest wedge.** "What's the smallest version someone would pay real money for this
week, not after the platform is built?" Push until: one feature, one workflow, shippable in
days. Red flag: "we need the full platform first." Bonus: "What if the user had to do nothing
at all to get value: no login, no integration, no setup?"

**Q5. Observation and surprise.** "Have you watched someone use this without helping? What
surprised you?" Red flags: "we sent a survey", "demo calls went well", "nothing surprising".
The gold: users doing something the product was not designed for.

**Q6. Future-fit.** "If the world looks meaningfully different in 3 years, does this become
more essential or less?" Push until: a specific claim about how users' world changes and why
that favors this product. "The market grows 20% a year" is not a thesis.

Then close the brief with three product questions every stage answers:
- **The 10-star version:** if time and money were unlimited, what would the user feel?
  Start from experience, not architecture. Then name the version 10x more valuable for 2x
  the effort.
- **The anti-goal:** what are you explicitly NOT building?
- **How do you know it's working?** One metric, not vibes, with the number that means yes.

**Smart-skip:** skip any question an earlier answer already covered.
**Escape hatch:** if the user says "just do it" or "skip the questions": "The hard questions
are the value. Two more, then we move." Ask the two most critical remaining questions for
their stage. A second push-back: proceed immediately; never ask a third time. A full skip
only when the user brings real evidence (existing users, revenue, named customers), and even
then run the premise challenge.

**Premise challenge** (always, before the recommendation):
1. Is this the right problem? Could a different framing give a dramatically simpler or bigger result?
2. What happens if nothing is built? Real pain or hypothetical?
3. What existing product, tool, or code already partially solves it?
4. If the deliverable is a new artifact (app, package, CLI), how will users get it? No distribution plan is a gap.

Write premises as statements the user must accept:

```
PREMISES:
1. [statement]: agree/disagree?
2. [statement]: agree/disagree?
```

A rejected premise sends you back to revise the understanding.

**Output:** `PRODUCT-BRIEF.md` with: problem statement, demand evidence, status quo, target
user and narrowest wedge, premises (accepted), 10-star version, anti-goal, success metric,
risks, open questions, a **go / no-go / not yet** recommendation with the evidence that
would flip it, and **the assignment**: one concrete action for this week (not a strategy).

If the result is "yes, build this," the next lane is `product-capability` (capability
contract) or `intent-driven-development` (design and acceptance criteria), not more
founder-theater.

### Mode 2: Founder Review

Reviews the current project through a founder lens:

```
1. Read README, CLAUDE.md, package.json, recent commits
2. Infer: what is this trying to be?
3. Score: product-market fit signals (0-10)
   - Usage growth trajectory
   - Retention indicators (repeat contributors, return users)
   - Revenue signals (pricing page, billing code, payment integration)
   - Competitive moat (what's hard to copy?)
4. Identify: the one thing that would 10x this
5. Flag: things being built that don't matter (focus as subtraction: the main value-add is what NOT to do)
```

### Mode 3: User Journey Audit

Maps the actual user experience:

```
1. Clone/install the product as a new user
2. Document every friction point (confusing steps, errors, missing docs)
3. Time each step
4. Compare to competitor onboarding
5. Score: time-to-value (how long until the user gets their first win?)
6. Recommend: top 3 fixes for onboarding
```

### Mode 4: Feature Prioritization

When there are 10 ideas and room for 2:

```
1. List all candidate features
2. Score each on: impact (1-5) × confidence (1-5) ÷ effort (1-5)
3. Rank by ICE score
4. Apply constraints: runway, team size, dependencies
5. Output: prioritized roadmap with rationale
```

### Mode 5: Scope Review (CEO lens on an existing plan)

Challenge a plan's scope before engineering review. No code changes.

**0A. Premise challenge:** right problem? The actual user or business outcome, and whether
the plan is the most direct path to it or solves a proxy? What if nothing is done?

**0B. Existing leverage:** map every sub-problem to what already exists; is anything rebuilt
that could be reused?

**0C. Dream state:**

```
  CURRENT STATE          THIS PLAN              12-MONTH IDEAL
  [describe]    --->     [delta]       --->     [target]
```

Does this plan move toward the ideal or away from it?

**0D. Pick a mode.** Present four options with a recommendation, and let the user choose:

| Mode | Posture | Default when |
|------|---------|--------------|
| SCOPE EXPANSION | Push scope up. 10x check, platonic ideal, at least 5 delight opportunities (adjacent 30-minute improvements). Recommend enthusiastically. | greenfield feature; user says "go big" |
| SELECTIVE EXPANSION | Hold scope as the baseline, make it bulletproof, and surface each expansion separately with neutral effort and risk. | enhancement of an existing system; user says "show me options" |
| HOLD SCOPE | Scope accepted. Make it bulletproof. No expansions. | bug fix, refactor |
| SCOPE REDUCTION | Find the minimum that ships value. Separate "must ship together" from "nice to ship together". | plan touches more than 15 files |

Complexity smell in HOLD and SELECTIVE: more than 8 files or more than 2 new classes or
services; challenge whether fewer moving parts reach the same goal.

**The user is in control.** Every scope change is an explicit opt-in, one decision per
question: **A)** add to this plan, **B)** defer to TODOS.md, **C)** skip. Never silently add or
remove scope. Once a mode is chosen, commit to it: raise concerns once, then do not drift
(no arguing for less work in EXPANSION, no sneaking scope back in REDUCTION).

**0E. Temporal interrogation** (EXPANSION, SELECTIVE, HOLD): what will the implementer need
to decide in hour 1 (foundations), hours 2-3 (core logic), hours 4-5 (integration), hour 6+
(polish and tests)? Surface those decisions now as questions, not "figure it out later".

**Output:** chosen mode, accepted and deferred scope, a "NOT in scope" list with one-line
reasons, the dream-state delta, and the open decisions. Hand the revised plan to `blueprint`
for the engineering review gate.

**Thinking instincts** to apply throughout (not a checklist): classify decisions by
reversibility and magnitude (most are two-way doors: move fast); invert ("what would make
this fail?"); focus as subtraction; speed calibration (70% of the information is enough except
for irreversible, high-magnitude calls); proxy skepticism (is the metric still serving users?);
leverage (small inputs, large outputs); design for trust.

## Output

All modes output actionable docs, not essays. Every recommendation has a specific next step.

## Integration

Pair with:
- `/browser-qa` to verify the user journey audit findings
- `/design-system audit` for visual polish assessment
- `/canary-watch` for post-launch monitoring
- `product-capability` when the product brief needs to become an implementation-ready capability plan
- `intent-driven-development` when the product is settled and the design is not
- `blueprint` after a Mode 5 scope review, for the engineering review gate
