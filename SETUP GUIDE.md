# Neva, setup

An assistant that runs on your machine, remembers in plain markdown you can open in Obsidian,
and answers from your notes rather than from guessing. Follow the steps in order. It takes
about thirty minutes, and most of that is the conversation in step 2.

If you only read one other thing, read [docs/00-testing-this.md](docs/00-testing-this.md). It
says honestly what is proven and what is not.

---

### STEP 0: what you need first

Two things, and you may already have both:

- **Claude Code**, or the Claude desktop app with this folder open as its project.
  https://code.claude.com/docs/en/quickstart
- **Obsidian**, to read your own notes: https://obsidian.md

That is the whole list. Claude Code is already signed in and already reads this folder, so
your assistant has a model and its instructions from the first minute. Nothing to install, no
key to paste, no server to run.

On a Mac this is well tested. On Linux you would be the first to try it.

---

### STEP 1: say "start"

Open this folder with your agent and tell it:

> *start*

It reads START.md, asks you about six questions about your work and how you like to be spoken
to, and builds the whole system behind the conversation. Your goals, your projects and its
personality all come out of that one conversation. It ends by doing a real task for you.

You never touch a terminal unless you want to.

**Prefer to do it yourself?** Run `./install.sh`, answer three questions, then fix anything
`doctor` marks FAIL. Each row names its own fix.

---

### STEP 2: check it is honest

Ask it something that is in your notes, and something that is not.

It should name the file it read for the first, and say plainly that it does not have the second.
If it ever answers the second one confidently, that is the bug this whole project exists to
prevent, and we want to hear about it.

---

### STEP 3, optional: put it on your phone and keep it running

Everything above works inside Claude Code, which means it stops when you close the window.

If you want the same assistant on Telegram, answering while your laptop is shut, that is the
upgrade: it needs [openclaw](https://docs.openclaw.ai/install), Node 22 or newer, and its own
model login, which is [docs/01a-model.md](docs/01a-model.md).

> [docs/02-telegram.md](docs/02-telegram.md)

Do this only once step 2 works. It is a different piece of software with its own setup, and
it is where most people get stuck, so there is no reason to face it before you know you want
what it gives you.

---

### STEP 4, optional: the background jobs, one at a time

> [docs/03-scheduled-jobs.md](docs/03-scheduled-jobs.md)

Part of the same optional upgrade, and only relevant once step 3 is done. They watch its health,
rotate its session before long conversations make it sloppy, and keep your notes synced. Turn
them on one at a time and watch each run once. Never all at once, and never on the day you
install.

---

### If something breaks

[docs/07-troubleshooting.md](docs/07-troubleshooting.md) is indexed by the exact error text, so
paste what you saw and find the row.

Everything else: [docs/](docs/) is numbered in reading order.
