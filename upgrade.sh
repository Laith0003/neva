#!/bin/bash
# upgrade.sh: replace template-owned paths only. Your content is never touched.
# Usage: run from a NEW template version's folder; pass your install prefix if custom.
set -eu
REPO="$(cd "$(dirname "$0")" && pwd)"
say() { printf "%s\n" "$*"; }
say "This updates: tools (bin/lib), services templates, docs, base persona layers, vault manual and skills."
say "It never touches: identity.env, USER.md, SOUL.local.md, AGENTS.local.md, or your vault content."
# NON-INTERACTIVE MODE (2026-08-01): install.sh's own `ask()` already handles an agent-driven,
# hands-free run (NEVA_NONINTERACTIVE=1 or no tty): pre-seeded answers pass through, a missing
# required one fails loudly by name. upgrade.sh had none of that: a hands-free invocation hit
# a bare `read` that returns empty, "" != "y", and the script exited 1 with no explanation at
# all, unlike every other entry point in this template. Match install.sh's contract.
if [ "${NEVA_NONINTERACTIVE:-0}" = "1" ] || [ ! -t 0 ]; then
  case "${UPGRADE_CONFIRM:-}" in
    y|Y|yes|YES|Yes) : ;;
    *)
      echo "non-interactive upgrade: missing confirmation (UPGRADE_CONFIRM)" >&2
      echo "fix: export UPGRADE_CONFIRM=yes and re-run, or run interactively" >&2
      exit 64
      ;;
  esac
else
  printf "Continue? [y/N]: "; read -r OK; [ "$OK" = "y" ] || exit 0
fi
bash "$REPO/install.sh"
say "Upgraded. Base persona layers were refreshed; your local layers won."
