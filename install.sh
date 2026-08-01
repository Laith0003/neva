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
    say "It will NOT be touched. The agent can import it later (your notes end up in OLD_VAULT/ inside the new structure)."
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
NTFY_TOPIC="${NTFY_TOPIC:-}"
ACTIVE_HOURS_START="${ACTIVE_HOURS_START:-08:00}"
ACTIVE_HOURS_END="${ACTIVE_HOURS_END:-22:00}"
QUIET_DAYS="${QUIET_DAYS:-}"
LEDGER_FILE="${LEDGER_FILE:-$VAULT_PATH/05 Money/2026.journal}"
FOOD_DIR="${FOOD_DIR:-$VAULT_PATH/Food}"
EOF
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
say "scheduled-job templates rendered to $RENDERED (enable later, one at a time: docs/03-scheduled-jobs.md)"

# ---------- 7. doctor ----------
echo
"$PREFIX/bin/doctor" || true
echo
say "Next: docs/01-first-run.md  (terminal first; Telegram comes after your first success)"
