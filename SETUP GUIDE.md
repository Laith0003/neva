# Neva, setup

An assistant that runs on your machine, remembers in plain markdown you can open in Obsidian,
and answers from your notes rather than from guessing. Follow the steps in order. It takes
about thirty minutes, and most of that is the conversation in step 2.

If you only read one other thing, read [docs/00-testing-this.md](docs/00-testing-this.md). It
says honestly what is proven and what is not.

---

### STEP 0: what you need first

- A **Mac**. Linux is included but has never been run end to end, so on Linux you are the first.
- **Node 22 or newer**: `node --version`
- **An AI coding agent** in this folder: Claude Code, or the Claude desktop app with this folder
  as its project. Install: https://code.claude.com/docs/en/quickstart
- **openclaw**: https://docs.openclaw.ai/install
- **Obsidian**, to read your own notes: https://obsidian.md

---

### STEP 1: give it a brain

This is the step people miss, and without it everything installs fine and then cannot answer
anything.

Your assistant needs a model: either a Claude subscription you log into, or an API key.

> Read [docs/01a-model.md](docs/01a-model.md) and do what it says. Two minutes if you have a
> Claude subscription.

---

### STEP 2: say "start"

Open this folder with your agent and tell it:

> *start*

It reads START.md, asks you about six questions about your work and how you like to be spoken
to, and builds the whole system behind the conversation. Your goals, your projects and its
personality all come out of that one conversation. It ends by doing a real task for you.

You never touch a terminal unless you want to.

**Prefer to do it yourself?** Run `./install.sh`, answer three questions, then fix anything
`doctor` marks FAIL. Each row names its own fix.

---

### STEP 3: check it is honest

Ask it something that is in your notes, and something that is not.

It should name the file it read for the first, and say plainly that it does not have the second.
If it ever answers the second one confidently, that is the bug this whole project exists to
prevent, and we want to hear about it.

---

### STEP 4: Telegram, when you want it on your phone

> [docs/02-telegram.md](docs/02-telegram.md)

Do this only after step 3 works. It walks you through making your own bot and locking it to
your account so nobody else can talk to your assistant.

---

### STEP 5: the background jobs, one at a time

> [docs/03-scheduled-jobs.md](docs/03-scheduled-jobs.md)

These are what keep it from rotting: they watch its health, rotate its session before long
conversations make it sloppy, and keep your notes synced. Turn them on one at a time and watch
each one run once. Never all at once, and never on the day you install.

---

### If something breaks

[docs/07-troubleshooting.md](docs/07-troubleshooting.md) is indexed by the exact error text, so
paste what you saw and find the row.

Everything else: [docs/](docs/) is numbered in reading order.
