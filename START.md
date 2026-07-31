# START: the hands-free installation

You are an AI agent reading this because a person opened this folder and said "start" (or
"install", "set me up", or similar). You drive the entire installation. They should never
need a terminal; you run the commands, they answer questions in chat.

Work through the steps IN ORDER. After every step, tell them in one line what just
happened. If a step fails, read the error, fix what you can yourself, and only hand them an
action when it genuinely needs a human (an install password, a phone tap). Never dump raw
logs on them; name the problem and the fix.

## Step 0: look before touching

Run: `uname` and `ls` of this folder. Confirm you are on macOS or Linux (Windows: stop and
tell them WSL2 is the supported path). Read `README.md` yourself so you can answer
questions about what this is.

## Step 1: dependencies

Check for git, curl, python3 (`command -v ...`). If missing on macOS, run
`xcode-select --install` for them and say a system dialog will appear. Check for openclaw;
if missing, install it per https://docs.openclaw.ai/install (show them the one command you
are running and what it does). openclaw needs Node 22+; check and install that first if
needed.

## Step 2: the three questions, in chat

Ask, one message at a time, reacting to each answer:
1. Their name.
2. What they want to call their agent. Do not suggest names.
3. Where the vault should live, offering `~/Vault` as the default, and explain in one line
   what the vault is (their notes, their agent's memory, plain files they own).

Detect the timezone yourself (`readlink /etc/localtime`); confirm it in passing rather than
asking.

## Step 3: run the installer, hands-free

Run from this folder:

```
OWNER_NAME="<their name>" AGENT_NAME="<agent name>" TIMEZONE="<tz>" \
VAULT_PATH="<vault path>" LUCY_NONINTERACTIVE=1 bash install.sh
```

The installer is idempotent and never overwrites existing content. If it reports a
non-empty folder at the vault path, relay that and ask whether to use it as-is or pick a
new path, then re-run with their answer.

## Step 4: read doctor's table and act on it

The installer ends by running `doctor`. Read every row yourself:
- Each FAIL row names its fix. Apply the fixes you can (starting the gateway, PATH note),
  then re-run `doctor` to confirm.
- WARN rows about telegram and scheduled jobs are EXPECTED at this stage; tell them so.
- Do not continue until FAILs are zero.

## Step 5: hand over to the persona interview

The workspace now contains BOOTSTRAP.md, the agent's own first-conversation script. If YOU
are the agent who will live here (openclaw agent in this workspace), read it and begin: it
is your script, six questions, one at a time. If you are a setup-only agent (e.g. Claude
Code doing the install), start a first conversation for them:
`openclaw agent --agent main --message "hello"` and tell them their agent will now
introduce itself and take over.

## Step 6: end in value

After the interview finishes (or if they skip it), ask for one real task and complete it.
The first session must end with something done, not with setup.

## What you must NOT do

- Do not enable scheduled jobs now. That is docs/03, later, one at a time, after Telegram.
- Do not touch Telegram yet. Terminal success first; then walk them through docs/02
  yourself, including LOCKING allowFrom to their numeric id before the first message.
- Do not skip the vault-exists safeguard, ever. Their existing notes outrank this install.
- Do not print any token or credential into the chat, even if asked while debugging.
