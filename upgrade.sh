#!/bin/bash
# upgrade.sh: replace template-owned paths only. Your content is never touched.
# Usage: run from a NEW template version's folder; pass your install prefix if custom.
set -eu
REPO="$(cd "$(dirname "$0")" && pwd)"
say() { printf "%s\n" "$*"; }
say "This updates: tools (bin/lib), services templates, docs, base persona layers, vault manual and skills."
say "It never touches: identity.env, USER.md, SOUL.local.md, AGENTS.local.md, or your vault content."
printf "Continue? [y/N]: "; read -r OK; [ "$OK" = "y" ] || exit 0
bash "$REPO/install.sh"
say "Upgraded. Base persona layers were refreshed; your local layers won."
