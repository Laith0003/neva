# Models: give your assistant a brain

Your assistant cannot work without a model. It has no knowledge, no memory, and no way to reason
until it can reach an LLM to think with. This step comes BEFORE Telegram, BEFORE scheduled jobs,
BEFORE anything else. Without it, install succeeds silently and the assistant is mute.

OpenClaw (the gateway this product uses) can work with multiple models. This page covers the two
most common paths. Pick one, follow the steps for that path, and verify it works before moving on.

## Which path is for you

**I have a Claude subscription (at claude.ai or through a paid plan).**
Go to "Path 1: OAuth login". This is simpler than managing API keys. Your subscription includes
a monthly credit; nothing costs extra to set up. Takes 2 minutes.

**I want to use an API key (Claude, OpenAI, or another provider).**
Go to "Path 2: API key". You control the key, the costs, and the billing. If you are already
using Claude API keys elsewhere, this is faster. Takes 5 minutes and requires pasting one
credential into one file.

**I have Ollama or another local model running on this machine.**
Path 3 is not documented here yet. Read https://docs.openclaw.ai/models/configure for the full
list of supported models and how to point openclaw at each one. Come back to this page once
you have chosen a model backend and updated ~/.openclaw/openclaw.json.

---

## Path 1: OAuth login (Claude subscription)

This uses your existing Claude.ai login. No API key needed, no monthly billing to manage beyond
your Claude subscription.

**Step 1: start the gateway**

Before any of this, start OpenClaw's gateway:

```bash
openclaw gateway
```

It runs in the foreground. Leave it running; open a new terminal for the next steps.

**Step 2: trigger the login flow**

In a new terminal, run:

```bash
openclaw models auth signin
```

This opens your browser to claude.ai and asks you to log in (if you are not already). After you
log in and approve, the browser closes automatically and you are done.

**Step 3: verify it works**

Run:

```bash
openclaw models auth list
```

You should see:

```
Profiles: claude (active)
```

If you see `Profiles: (none)`, the login did not work. Go back to Step 2 and check the browser
window; sometimes the approval page is hidden behind another window.

**Step 4: test the assistant**

In the same terminal, run:

```bash
openclaw agent --agent main --message "who am I"
```

If your assistant responds with a question (this is its first run, so it should ask your name),
the model is working. If you see an error like "authentication failed" or "no model configured",
go back to Step 3 and re-verify the profile list.

---

## Path 2: API key (pay-as-you-go)

This uses an API key from your model provider. You pay for every request, with no monthly
commitment. Useful if you want fine-grained billing or are testing before committing to a
subscription.

### 2a: Claude API key

Go to https://console.anthropic.com/keys and create a new API key. Copy it (it is long and
starts with `sk-ant-`).

The key is a secret. Never paste it into chat, a terminal, a URL, or any message anyone can
read. It gives anyone who has it access to your account and your billing. Treat it like a
password.

**Where it goes:**

The key lives in `~/.openclaw/openclaw.json`, a file that is never synced or backed up (it
stays on your machine only). OpenClaw reads it, but only your machine ever sees the raw text.

**Step 1: create the config file**

If this is your first time using OpenClaw, create the config:

```bash
openclaw config get models > ~/.openclaw/openclaw.json
```

If the file already exists (from a prior setup), skip this step.

**Step 2: add your key**

Edit `~/.openclaw/openclaw.json` in your text editor:

```bash
# macOS
open ~/.openclaw/openclaw.json

# Linux
$EDITOR ~/.openclaw/openclaw.json
```

Find the line that mentions `ANTHROPIC_API_KEY` or find the `models` section. Add or replace
this block:

```json
"models": {
  "default": "claude-opus-4-1",
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  }
}
```

Paste your actual API key (the long string starting with `sk-ant-`) where it says `sk-ant-...`.
Do not add quotes around the braces; JSON is strict about format.

Save the file (macOS Cmd+S, Linux Ctrl+S or your editor's save).

**Step 3: verify it works**

Run:

```bash
openclaw models auth list
```

You should see:

```
Profiles: claudeapi (active)
```

If you see `parse-error` or the file is malformed, check the JSON again: every `{` needs a
matching `}`, every comma except before `}` is required, and strings must use `"` not `'`.

**Step 4: test the assistant**

```bash
openclaw agent --agent main --message "who am I"
```

If your assistant responds, the model is working.

### 2b: OpenAI API key

Similar to Claude, but the key comes from https://platform.openai.com/account/api-keys.

Edit `~/.openclaw/openclaw.json` and add:

```json
"models": {
  "default": "gpt-4o",
  "providers": {
    "openai": {
      "apiKey": "sk-..."
    }
  }
}
```

The rest is the same: verify with `openclaw models auth list`, then test with `openclaw agent`.

---

## What happens next

Once your model is working, move to:

1. [docs/01-first-run.md](01-first-run.md): run install.sh and the setup interview
2. [docs/02-telegram.md](02-telegram.md): wire up Telegram so your assistant can reach you
3. [docs/03-scheduled-jobs.md](03-scheduled-jobs.md): enable the review nudge and other timers

---

## Troubleshooting

**"no model configured" or "authentication failed"**

Run `openclaw models auth list` and check the output. If it says `Profiles: (none)`, no model
is active. Go back to your path above and re-run Step 3. On Linux, you may need to restart the
gateway for changes to take effect:

```bash
pkill openclaw
openclaw gateway
```

**"Could not parse ~/.openclaw/openclaw.json"**

The JSON file has a syntax error. Open it, check for:
- Every `{` has a matching `}`
- Every `"` (quote) starts a string and another `"` ends it
- Commas are after every item except the last one before a `}` or `]`

If you have made a backup, delete the bad file and start fresh with Step 1 or 2a.

**"Profiles: (none)" after following Path 1**

The browser login was not approved. Go back to your browser and visit https://claude.ai directly,
then try `openclaw models auth signin` again. The browser window may appear behind other windows.

**My model kept working, but now it does not**

Run `doctor` and check the rows about openclaw. If a model was working before and stopped,
either the token expired (reauthorize with Step 2 or 3 of your path) or the gateway is not
running.

**I want to switch models**

Run `openclaw models auth list` to see what is active. To change to a different model, follow
the path for that model (Path 1 or Path 2a or 2b) and complete Step 3. The most recent one to
authenticate becomes active.

---

See https://docs.openclaw.ai/models/configure for advanced configuration (local models, custom
endpoints, etc.) and https://docs.openclaw.ai/cli/models for the full command reference.
