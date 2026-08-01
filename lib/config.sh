#!/bin/bash
# Shared config reader for all shell tools. Source this at the top of every bin/ tool:
#
#   . "$(dirname "$0")/../lib/config.sh"   # or: . /usr/local/lib/neva/config.sh
#
# It validates and sources ~/.config/neva/identity.env, then guarantees every required key
# is set. Fails loudly with the exact fix, never silently with an empty variable: an unset
# OWNER_CHAT_ID becoming "" is how messages end up nowhere.
set -u

NEVA_CONFIG="${NEVA_CONFIG:-$HOME/.config/neva/identity.env}"

if [ ! -f "$NEVA_CONFIG" ]; then
  echo "config missing: $NEVA_CONFIG" >&2
  echo "fix: run install.sh (it interviews you and writes this file)" >&2
  exit 78   # EX_CONFIG
fi

# refuse world/group-readable config: it holds a chat id and personal identity
PERMS=$(stat -f "%Lp" "$NEVA_CONFIG" 2>/dev/null || stat -c "%a" "$NEVA_CONFIG" 2>/dev/null)
case "$PERMS" in
  600|400) : ;;
  *) echo "config perms are $PERMS, must be 600: chmod 600 '$NEVA_CONFIG'" >&2; exit 78 ;;
esac

# only accept KEY="value" lines; anything else in the file is a syntax error, not code to run
if grep -qvE '^([A-Z_]+="[^"]*"|#.*|\s*)$' "$NEVA_CONFIG"; then
  echo "config has invalid lines (only KEY=\"value\" and comments allowed):" >&2
  grep -nvE '^([A-Z_]+="[^"]*"|#.*|\s*)$' "$NEVA_CONFIG" | head -3 >&2
  exit 78
fi

# shellcheck disable=SC1090
. "$NEVA_CONFIG"

for KEY in OWNER_NAME AGENT_NAME TIMEZONE VAULT_PATH WORKSPACE_PATH; do
  if [ -z "${!KEY:-}" ]; then
    echo "config key $KEY is empty in $NEVA_CONFIG" >&2
    echo "fix: edit the file or re-run install.sh" >&2
    exit 78
  fi
done

# expand a literal $HOME left by the example file
VAULT_PATH="${VAULT_PATH/#\$HOME/$HOME}"
WORKSPACE_PATH="${WORKSPACE_PATH/#\$HOME/$HOME}"
LEDGER_FILE="${LEDGER_FILE/#\$HOME/$HOME}"
FOOD_DIR="${FOOD_DIR/#\$HOME/$HOME}"

# OWNER_CHAT_ID is intentionally allowed to be empty until Telegram is set up. Tools that
# actually send must check it themselves rather than posting to a placeholder id.
neva_can_send() { [ -n "${OWNER_CHAT_ID:-}" ]; }
