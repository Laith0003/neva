#!/bin/bash
# install.sh: the only entry point. Safe to re-run any time; never overwrites your content.
#
# What it does, in order:
#   1. checks your platform and dependencies (nothing installed without telling you)
#   2. copies the tools to ~/.local/lucy and links them into ~/.local/bin (no sudo, ever)
#   3. sets up your vault folder (or leaves your existing one completely alone)
#   4. interviews you for the identity file (only what it cannot detect)
#   5. seeds the agent workspace (BOOTSTRAP interview, base persona layers)
#   6. renders the scheduled-job templates (does NOT enable them; that is a later, manual,
#      one-at-a-time step: docs/03-scheduled-jobs.md)
#   7. runs doctor so you end with a table of what works and what to do next
set -u
REPO="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local/lucy"
BIN="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/lucy"
CONFIG="$CONFIG_DIR/identity.env"
STATE="$HOME/.local/state/lucy"

say()  { printf "%s\n" "$*"; }
ask()  { # ask VAR "question" "default"
  local var="$1" q="$2" def="${3:-}" cur
  cur="${!var:-}"
  if [ -n "$cur" ]; then return 0; fi     # already answered (env pre-seed or re-run)
  # hands-free mode: an agent collects answers in chat and passes them as env vars.
  # If a required answer is missing here, fail with its name instead of hanging on read.
  if [ "${LUCY_NONINTERACTIVE:-0}" = "1" ] || [ ! -t 0 ]; then
    if [ -n "$def" ]; then eval "$var=\"\$def\""; return 0; fi
    echo "non-interactive install: missing required answer $var ($q)" >&2
    echo "fix: export $var=... and re-run, or run interactively" >&2
    exit 64
  fi
  if [ -n "$def" ]; then
    printf "%s [%s]: " "$q" "$def"
  else
    printf "%s: " "$q"
  fi
  read -r REPLY
  eval "$var=\"\${REPLY:-\$def}\""
}

# ---------- 1. platform + deps ----------
OS="$(uname)"
case "$OS" in
  Darwin|Linux) : ;;
  *) say "This installer supports macOS and Linux. Windows is not supported (WSL2 works: run it inside your WSL2 home)."; exit 1 ;;
esac

MISSING=""
for D in git curl python3; do command -v "$D" >/dev/null 2>&1 || MISSING="$MISSING $D"; done
if [ -n "$MISSING" ]; then
  say "Missing required tools:$MISSING"
  [ "$OS" = "Darwin" ] && say "fix: xcode-select --install   (or: brew install$MISSING)"
  [ "$OS" = "Linux" ]  && say "fix: sudo apt install$MISSING   (or your distro's equivalent)"
  exit 1
fi
command -v openclaw >/dev/null 2>&1 || say "note: openclaw is not installed yet. The tools install fine without it; install it before first run: https://docs.openclaw.ai/install"
command -v rg >/dev/null 2>&1 || say "note: ripgrep (rg) recommended for fast vault search: brew/apt install ripgrep"

# ---------- 2. tools ----------
mkdir -p "$PREFIX" "$BIN" "$STATE"
cp -R "$REPO/bin" "$REPO/lib" "$PREFIX/"
# tools resolve lib relative to the repo; installed copies use the fixed prefix instead
for F in "$PREFIX/bin/"*; do
  [ -f "$F" ] || continue
  sed -i.bak 's|^\. "\$(cd "\$(dirname "\$0")/\.\." && pwd)/lib/config.sh"|. "'"$PREFIX"'/lib/config.sh"|' "$F" && rm -f "$F.bak"
  chmod +x "$F"
  ln -sf "$F" "$BIN/$(basename "$F")"
done
say "tools installed to $PREFIX/bin and linked into $BIN"
case ":$PATH:" in
  *":$BIN:"*) : ;;
  *) say "note: $BIN is not in your PATH. Add to your shell rc:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# ---------- 3. vault ----------
# shellcheck disable=SC1090
[ -f "$CONFIG" ] && . "$CONFIG"
ask VAULT_PATH "Where should your vault live" "$HOME/Vault"
VAULT_PATH="${VAULT_PATH/#\~/$HOME}"
if [ -d "$VAULT_PATH" ] && [ -n "$(ls -A "$VAULT_PATH" 2>/dev/null)" ]; then
  if [ -f "$VAULT_PATH/.lucy-template" ]; then
    say "vault exists at $VAULT_PATH (ours), leaving it alone"
  else
    say "A non-empty folder already exists at $VAULT_PATH."
    # 2026-08-01: this used to promise an automatic import into a specifically-named backup
    # subfolder. No code anywhere creates that folder or does that import; a buyer with an
    # existing vault is exactly the buyer most afraid of losing their notes, so a promise that
    # cashes out to nothing here is actively harmful. Say only what actually happens.
    say "It will NOT be touched, and nothing here imports it automatically. Point VAULT_PATH at a new empty folder to keep both, or tell your agent to fold the old notes in by hand once it is running."
    ask VAULT_CONFIRM "Type a different path for the new vault, or press enter to use the existing folder as-is" "$VAULT_PATH"
    VAULT_PATH="${VAULT_CONFIRM/#\~/$HOME}"
  fi
fi
if [ ! -d "$VAULT_PATH" ] || [ -z "$(ls -A "$VAULT_PATH" 2>/dev/null)" ]; then
  mkdir -p "$VAULT_PATH"
  cp -R "$REPO/vault/." "$VAULT_PATH/"
  date +%F > "$VAULT_PATH/.lucy-template"
  say "vault created at $VAULT_PATH"
fi
# vault-sync needs a repo; without one it fails every 2 minutes into a log nobody reads
if [ ! -d "$VAULT_PATH/.git" ] && command -v git >/dev/null 2>&1; then
  ( cd "$VAULT_PATH" && git init -q && git add -A 2>/dev/null \
    && git -c user.email="agent@local" -c user.name="${OWNER_NAME:-owner}" \
       commit -q -m "vault initial commit" 2>/dev/null ) && say "vault is now a git repo (history for every change)"
fi

# ---------- 4. identity interview (only the undetectable) ----------
mkdir -p "$CONFIG_DIR"
DETECTED_TZ="$( (readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||') || true)"
[ -z "$DETECTED_TZ" ] && DETECTED_TZ="UTC"
ask OWNER_NAME  "Your name" ""
ask AGENT_NAME  "What do you want to call your agent (you can change this in its first conversation)" "Assistant"
ask TIMEZONE    "Timezone" "$DETECTED_TZ"
# chat id is detected later by the agent itself on Telegram; email/phone only when an
# integration needs them. We do not collect what we do not use.
# Left EMPTY on purpose. The agent fills it when the buyer first messages on Telegram.
# Writing a placeholder like "unset" here would satisfy every non-empty check in the
# system and send every alert to chat_id=unset forever, failing silently.
OWNER_CHAT_ID="${OWNER_CHAT_ID:-}"
OWNER_EMAIL="${OWNER_EMAIL:-}"
OWNER_PHONE="${OWNER_PHONE:-}"
WORKSPACE_PATH="${WORKSPACE_PATH:-$HOME/.openclaw/workspace}"

# TOCTOU fix (2026-08-01): `cat > "$CONFIG"` used to create this file under the caller's
# default umask (typically 022, world-readable) and only chmod 600 it AFTER the identity
# and chat-id were already written to disk. Between those two steps the file held a live
# chat id (and, once Telegram is wired, a route to the owner's private assistant) readable
# by any other local account. umask 077 makes the file 600 from the instant it is created,
# so there is no window where it is anything else; the trailing chmod stays as a defensive
# no-op for the case where a prior install left it looser.
( umask 077
cat > "$CONFIG" <<EOF
# Written by install.sh $(date +%F). Safe to edit; re-run install.sh keeps your answers.
OWNER_NAME="$OWNER_NAME"
AGENT_NAME="$AGENT_NAME"
OWNER_EMAIL="$OWNER_EMAIL"
OWNER_PHONE="$OWNER_PHONE"
OWNER_CHAT_ID="$OWNER_CHAT_ID"
TIMEZONE="$TIMEZONE"
VAULT_PATH="$VAULT_PATH"
WORKSPACE_PATH="$WORKSPACE_PATH"
MODEL_BACKEND="${MODEL_BACKEND:-claude-cli}"
ACTIVE_HOURS_START="${ACTIVE_HOURS_START:-08:00}"
ACTIVE_HOURS_END="${ACTIVE_HOURS_END:-22:00}"
QUIET_DAYS="${QUIET_DAYS:-}"
LEDGER_FILE="${LEDGER_FILE:-$VAULT_PATH/05 Money/2026.journal}"
FOOD_DIR="${FOOD_DIR:-$VAULT_PATH/Food}"
EOF
)
chmod 600 "$CONFIG"
say "identity written to $CONFIG (600)"

# ---------- 5. workspace ----------
mkdir -p "$WORKSPACE_PATH/skills"
for F in AGENTS.base.md SOUL.base.md; do
  cp "$REPO/workspace/$F" "$WORKSPACE_PATH/$F"     # base layers always update
done
# BOOTSTRAP only if the interview never ran (its self-deletion is the marker)
if [ ! -f "$WORKSPACE_PATH/USER.md" ] && [ ! -f "$WORKSPACE_PATH/BOOTSTRAP.md" ]; then
  cp "$REPO/workspace/BOOTSTRAP.md" "$WORKSPACE_PATH/BOOTSTRAP.md"
  say "BOOTSTRAP interview seeded: your agent's first conversation will be the setup"
fi
if [ -d "$REPO/workspace/skills" ]; then
  cp -R "$REPO/workspace/skills/." "$WORKSPACE_PATH/skills/" 2>/dev/null || true
fi

# ---------- 6. render service templates (not enabled) ----------
RENDERED="$PREFIX/services"
mkdir -p "$RENDERED"
render() { sed -e "s|@PREFIX@|$PREFIX|g" -e "s|@HOME@|$HOME|g" "$1" > "$2"; }
if [ "$OS" = "Darwin" ]; then
  for T in "$REPO/services/launchd/"*.tmpl; do
    [ -f "$T" ] || continue
    render "$T" "$RENDERED/$(basename "${T%.tmpl}")"
  done
else
  for T in "$REPO/services/systemd/"*.tmpl; do
    [ -f "$T" ] || continue
    render "$T" "$RENDERED/$(basename "${T%.tmpl}")"
  done
fi
# every job's Program/ExecStart routes through this: it writes a heartbeat line on every run
# regardless of the wrapped job's outcome, so doctor can tell "never fired" from "fired and
# failed" from "fired clean" without depending on OS-specific job state (see heartbeat-wrap.sh).
render "$REPO/services/heartbeat-wrap.sh" "$RENDERED/heartbeat-wrap.sh"
chmod +x "$RENDERED/heartbeat-wrap.sh"
say "scheduled-job templates rendered to $RENDERED (enable later, one at a time: docs/03-scheduled-jobs.md)"

# Linux systemd --user units only run while a user session exists, UNLESS lingering is
# enabled: without it, a timer enabled over SSH stops the moment that SSH session ends and
# never fires again, silently. This is the confirmed root cause of "the cadence timer has
# never fired once" on the founder's own VPS (2026-08-01: systemctl --user list-timers showed
# it loaded with last-run "-"). Best-effort, never fatal: some minimal hosts require root or
# lack polkit, and the buyer may not be root.
if [ "$OS" = "Linux" ] && command -v loginctl >/dev/null 2>&1; then
  ME="$(id -un)"
  if [ "$(loginctl show-user "$ME" --property=Linger --value 2>/dev/null)" = "yes" ]; then
    say "lingering already enabled for $ME (systemd --user timers keep running after you log out)"
  elif loginctl enable-linger "$ME" >/dev/null 2>&1; then
    say "enabled lingering for $ME: systemd --user timers now keep running after SSH logout"
  else
    say "note: could not enable lingering for $ME automatically."
    say "fix: sudo loginctl enable-linger $ME   (without this, every scheduled job here stops the moment you log out and never fires again)"
  fi
fi

# The README promises a review nudge when your notes go stale. Rendering the timer template
# is not the same as it running (this was the actual defect: install used to render-only and
# leave every job off, so the promise was OFF for every buyer by default, with nothing telling
# them so). Enable just the one flagship timer, with consent, same as every other interview
# question; the higher-blast-radius guards (lane-guard restarts the gateway, session-guard
# rotates your live session, vault-sync pushes to git) stay opt-in one-at-a-time on purpose,
# per docs/03-scheduled-jobs.md: enabling everything at once is a documented way these break.
ask ENABLE_CADENCE "Turn on the review-nudge timer now (checks once a day, nudges in Telegram only if Reviews/Journal/Strategy have gone stale)" "yes"
CADENCE_STATUS="off"
# TEST-HARNESS SAFETY VALVE (2026-08-01, added after this loaded a real job into the real
# logged-in account's launchd session TWICE in one afternoon while testing this exact feature
# on a real dev Mac): launchd and systemd --user are keyed to the real logged-in account, not
# to $HOME. Overriding HOME for an install into a throwaway sandbox does NOT sandbox
# `launchctl load` / `systemctl --user enable --now`; they still register against the real
# session, using whatever sandbox paths were rendered, and nothing about a scratch $HOME tells
# a test harness it needs to unload them afterward. A real buyer's real install should load for
# real; a test/CI run of this script should not. LUCY_SKIP_SCHEDULE_ENABLE=1 is the explicit,
# opt-in way to exercise the render+ask logic below without touching the host scheduler.
if [ "${LUCY_SKIP_SCHEDULE_ENABLE:-0}" = "1" ]; then
  say "cadence timer is OFF: LUCY_SKIP_SCHEDULE_ENABLE=1 (test/CI mode, real launchd/systemd not touched)"
else
case "$ENABLE_CADENCE" in
  y|Y|yes|YES|Yes)
    if [ "$OS" = "Darwin" ]; then
      LA="$HOME/Library/LaunchAgents"
      mkdir -p "$LA"
      cp "$RENDERED/com.lucy.cadence.plist" "$LA/com.lucy.cadence.plist"
      launchctl unload "$LA/com.lucy.cadence.plist" >/dev/null 2>&1
      if launchctl load -w "$LA/com.lucy.cadence.plist" 2>/dev/null; then
        CADENCE_STATUS="on"
      fi
    else
      UD="$HOME/.config/systemd/user"
      mkdir -p "$UD"
      cp "$RENDERED/lucy-cadence.service" "$RENDERED/lucy-cadence.timer" "$UD/"
      if systemctl --user daemon-reload >/dev/null 2>&1 \
         && systemctl --user enable --now lucy-cadence.timer >/dev/null 2>&1; then
        CADENCE_STATUS="on"
      fi
    fi
    ;;
esac
if [ "$CADENCE_STATUS" = "on" ]; then
  say "cadence timer is ON: it will nudge you in Telegram when Reviews/Journal/Strategy go stale"
else
  say "cadence timer is OFF: the 'drafts reviews when you go quiet' feature will not run"
  say "fix: enable it any time -> docs/03-scheduled-jobs.md (or answer yes on the next install.sh re-run)"
fi
fi
echo "$CADENCE_STATUS" > "$STATE/cadence-enabled-at-install"

# ---------- 7. doctor ----------
echo
"$PREFIX/bin/doctor" || true
echo
say "Next: docs/01-first-run.md  (terminal first; Telegram comes after your first success)"
