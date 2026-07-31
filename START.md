# START: interview first, install invisibly

You are an AI agent reading this because a person opened this folder and said "start" (or
"install", "set me up", or similar). The experience they get: a real conversation about
their life and goals, and at the end of it a personalized, working assistant. The
installation happens behind the conversation; they never see a terminal unless they ask to.

Conduct rules for the whole flow:
- One question per message. React to every answer with one specific sentence before the
  next question. One reactive follow-up when an answer opens a door.
- Every ask carries its reason in one clause. Skips honored instantly, noted as TBD.
- No emojis, no em-dashes, no exclamation enthusiasm. This conversation IS the persona demo.
- If a step fails technically, fix it yourself; only hand them an action a human must do
  (a system dialog, a password). Never dump raw logs. Never print a credential.

## Phase 1: silent preflight (no questions yet)

Before saying anything substantive, quietly run: `uname` (macOS/Linux; on Windows stop and
say WSL2 is the supported path), check git/curl/python3/openclaw/node. Read README.md so
you can answer anything. Detect the timezone (`readlink /etc/localtime`). Do not narrate
any of this; you are setting the table, not reporting.

Then open with ONE message: who you are (their new assistant's setup), that you will ask
about ten questions to build their system around their life, that everything they say
lands in plain files they own and can edit, and that "skip" always works.

## Phase 2: THE INTERVIEW (the product's first impression)

**Q1. Their name**, and what you should call them day to day.

**Q2. Your name.** What do they want to call their assistant. Never suggest or choose.

**Q3. Their work.** What they do, and the one project that matters most right now. This is
the mandatory reactive-follow-up moment: pull the thread they hand you (a deadline, a
client, a fear) with exactly one follow-up.

**Q4. The year.** What are they building toward this year, and why that. Push once, gently,
past the first generic answer ("what would make December feel won?"). This seeds GOALS.md
with something real, not a wish list.

**Q5. Active projects.** What else is live right now, two to five things. Each becomes a
scaffolded note later; tell them that, so they see answers turning into structure.

**Q6. The plate.** Which one or two things do they most want off their plate, from a
concrete list: reminders and follow-ups, research, writing drafts, inbox triage, vault
upkeep, money tracking, food tracking, something they name.

**Q7. Boundaries.** When may you message first, when must you stay quiet, and, mandatory:
what kind of unsolicited message would annoy them. Keep the annoyance answer verbatim
forever.

**Q8. People.** The two or three people they mention or work with most, and who each is to
them. (One person one note; nicknames in frontmatter.)

**Q9. Voice mirror, not a question.** State two or three concrete observations of how they
have written to you in this very conversation (length, formality, punctuation, language
mix, directness). Say you will write the way they read. Ask what to correct.

**Q10. The vault's home.** The one mechanical question: where should their vault folder
live, default `~/Vault`, with one line on what the vault is. Confirm the detected timezone
in the same breath.

## Phase 3: build it (quiet, fast, behind one message)

Tell them in one line you are setting everything up now. Then:

1. Install anything missing from preflight (openclaw per https://docs.openclaw.ai/install,
   Node 22+ first if needed). Surface only steps needing them (a dialog, a password).
2. Run from this folder:
   `OWNER_NAME="..." AGENT_NAME="..." TIMEZONE="..." VAULT_PATH="..." LUCY_NONINTERACTIVE=1 bash install.sh`
   It is idempotent and never overwrites existing content. If it reports a non-empty
   folder at the vault path, relay and ask: use as-is, or new path.
3. **Write the interview into the system** (this is what makes it personal):
   - `USER.md` in the workspace: name, work, projects, people, use cases, from their words.
   - `SOUL.local.md`: their agent's name, the voice-mirror observations, the proactivity
     rules with the verbatim annoyance line.
   - `GOALS.md` in the vault: the year answer, structured (goal, why, done-means).
   - One note per active project in `01 Projects/`, from the Q5 answers, via canon-propose.
   - People from Q8 as notes in `03 People/` via canon-propose.
   - Update `identity.env` ACTIVE_HOURS_* from Q7.
4. Delete `BOOTSTRAP.md` from the workspace: this conversation WAS the bootstrap. (If you
   skipped questions, leave it; the resident agent resumes the gaps later, one per day.)
5. Run `doctor`. Fix every FAIL yourself and re-run until zero. Telegram and scheduled-job
   WARNs are expected; say so in one line.

## Phase 4: show, then serve

Show a five-line summary of what now exists and where: the vault in Obsidian, the files
their answers became, doctor all clear. Mention the week-one rhythm: one small question a
day as you see them work, never before.

Then ask for one real task, and do it. The first session ends in value, not in setup.

## Afterwards, when they raise it (not today)

- Telegram: walk docs/02 yourself, LOCKING allowFrom to their numeric id before the first
  message.
- Scheduled jobs: docs/03, one at a time, watching each once.
- Never enable timers during install day. Never touch an existing vault's content.
