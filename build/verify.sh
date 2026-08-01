#!/bin/bash
# verify.sh: prove the product's PROMISES in a HOSTILE sandbox. Run before every release.
#
# Why this exists. Five blockers shipped past me because I tested that things ran without
# erroring, on a machine that shared its assumptions with the source machine:
#   - canon silently returned nothing without ripgrep; both my machines had ripgrep
#   - vault-sync failed instantly because nothing git-init'd the vault; I tested install
#     and vault-sync separately, never in the documented sequence
#   - OWNER_CHAT_ID was written as the string "unset", defeating every non-empty check;
#     I fixed the empty-variable symptom without tracing what consumes it
#   - doctor printed "all clear" over nine warnings meaning the agent was inert; I ran it,
#     saw "all clear", and believed my own tool instead of checking whether it was true
#   - canon-propose's gated path was never exercised, only the ungated one
#
# So this harness does the opposite of what I did:
#   1. HOSTILE env: fresh HOME, minimal PATH, dependencies deliberately hidden
#   2. SEQUENCE: runs the documented order, not isolated pieces
#   3. PROMISES: asserts what the README claims to a buyer, not that exit codes are 0
#   4. NEGATIVE controls: proves each check can actually fail
#
# Usage: bash build/verify.sh   (exit 0 = releasable)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
SANDBOX="$(mktemp -d /tmp/lucy-verify-XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT

ok()   { printf "  PASS  %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  FAIL  %s\n    -> %s\n" "$1" "$2"; FAIL=$((FAIL+1)); }
head_() { printf "\n%s\n" "$1"; }

# A deliberately impoverished PATH: no ripgrep, no hledger, no brew bin.
# This is the buyer's machine, not ours.
POOR_PATH="/usr/bin:/bin:/usr/sbin:/sbin"

head_ "1. install, hands-free, in a fresh HOME"
export HOME="$SANDBOX/home"; mkdir -p "$HOME"
OUT=$(OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
      VAULT_PATH="$HOME/MyVault" LUCY_NONINTERACTIVE=1 \
      PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" 2>&1)
if [ $? -eq 0 ]; then ok "installer completes non-interactively"; else bad "installer" "exit non-zero"; fi
[ -f "$HOME/.config/lucy/identity.env" ] && ok "identity file written" || bad "identity file" "missing"
P=$(stat -f "%Lp" "$HOME/.config/lucy/identity.env" 2>/dev/null || stat -c "%a" "$HOME/.config/lucy/identity.env" 2>/dev/null)
[ "$P" = "600" ] && ok "identity file is 600" || bad "identity perms" "got $P, want 600"

head_ "2. the placeholder-identity trap (B4)"
if grep -qE 'OWNER_CHAT_ID="(unset|none|todo|xxx)"' "$HOME/.config/lucy/identity.env"; then
  bad "chat id placeholder" "a placeholder string passes every non-empty check and sends to nowhere"
else ok "chat id is empty, not a placeholder string"; fi

head_ "3. vault is usable AND version-controlled (B3)"
[ -d "$HOME/MyVault/03 People" ] && ok "vault structure created" || bad "vault structure" "missing folders"
[ -d "$HOME/MyVault/.git" ] && ok "vault is a git repo (vault-sync depends on it)" || bad "vault git" "vault-sync will fail every run"

head_ "4. PROMISE: grounded answers work WITHOUT optional deps (B1)"
cat > "$HOME/MyVault/03 People/Jane Doe.md" <<'EOF'
# Jane Doe
Works at Contoso as the procurement lead.
EOF
R=$(HOME="$HOME" PATH="$POOR_PATH" python3 "$HOME/.local/lucy/bin/canon" "Contoso procurement" 2>&1)
if echo "$R" | grep -q "Jane Doe"; then ok "canon finds notes by CONTENT with no ripgrep"
else bad "canon content search" "returned nothing without rg; the agent would say 'I don't have that' about a note that exists"; fi
# negative control: the check must be able to fail
R2=$(HOME="$HOME" PATH="$POOR_PATH" python3 "$HOME/.local/lucy/bin/canon" "zzz totally absent topic" 2>&1)
if echo "$R2" | grep -q "No canon note matches"; then ok "negative control: absent topic still reports nothing"
else bad "negative control" "canon claims a match for an absent topic"; fi

head_ "5. PROMISE: doctor tells the truth about readiness (B5)"
D=$(HOME="$HOME" PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" "$HOME/.local/lucy/bin/doctor" 2>&1)
if echo "$D" | grep -q "^all clear$"; then
  bad "doctor honesty" "said 'all clear' with no gateway, no telegram, no timers: teaches buyers to ignore it"
else ok "doctor does not claim all-clear on an inert system"; fi
echo "$D" | grep -qi "cannot work yet\|failure" && ok "doctor names why it is not ready" || bad "doctor guidance" "no explanation of what is missing"

head_ "6. every FAIL row must carry an actionable fix"
BADROWS=$(echo "$D" | awk '/^  FAIL/ { if (length($0) < 45) print }')
[ -z "$BADROWS" ] && ok "all FAIL rows include a fix" || bad "bare FAIL rows" "$BADROWS"

head_ "7. tools fail loudly, never silently (config missing)"
BADTOOLS=""
for T in canon canon-lint cadence vault-sync food; do
  [ -x "$HOME/.local/lucy/bin/$T" ] || continue
  # execute via the shebang: several tools are python, bash cannot run them
  E=$(HOME="$SANDBOX/empty" PATH="$POOR_PATH" "$HOME/.local/lucy/bin/$T" 2>&1); RC=$?
  E="$E rc=$RC"
  echo "$E" | grep -qiE "config missing|install.sh|rc=78" || BADTOOLS="$BADTOOLS $T"
done
[ -z "$BADTOOLS" ] && ok "tools name the fix when unconfigured" || bad "silent tools:$BADTOOLS" "should exit 78 naming install.sh"

head_ "8. no tool claims an action it did not perform"
LIARS=""
for T in briefing alert; do
  [ -x "$HOME/.local/lucy/bin/$T" ] || continue
  HOME="$HOME" PATH="$POOR_PATH" "$HOME/.local/lucy/bin/$T" >/dev/null 2>&1
  if grep -rqi "sent" "$HOME/.local/state/lucy/$T.log" 2>/dev/null; then LIARS="$LIARS $T"; fi
done
[ -z "$LIARS" ] && ok "no false 'sent' in logs" || bad "tools logging phantom sends:$LIARS" "the product's own headline rule forbids this"

head_ "9. gated canon writes are not a one-way trapdoor (B2)"
G=$(printf 'A test money note.\n' | HOME="$HOME" PATH="$POOR_PATH" \
    python3 "$HOME/.local/lucy/bin/canon-propose" money "Verify Money Note" --mode new 2>&1)
if echo "$G" | grep -qi "sent to the owner\|GATED"; then
  if [ -x "$HOME/.local/lucy/bin/canon-approve" ] || echo "$G" | grep -qi "approve"; then
    ok "gated write is queued AND a drain path exists"
  else
    bad "gated write dead-letters" "queued for approval with no tool or documented way to approve it"
  fi
else ok "money write path completed without an unreachable gate"; fi

head_ "10. docs promise nothing that does not exist"
MISSINGDOC=""
for L in $(grep -rhoE '(docs/[a-z0-9/.-]+\.md)' "$REPO/README.md" "$REPO/docs" 2>/dev/null | sort -u); do
  [ -f "$REPO/$L" ] || MISSINGDOC="$MISSINGDOC $L"
done
[ -z "$MISSINGDOC" ] && ok "every referenced doc exists" || bad "dead doc links:$MISSINGDOC" "a buyer following the docs hits a wall"

head_ "11. no personal data in the artifact"
if python3 "$REPO/build/leak-scan.py" "$REPO" >/dev/null 2>&1; then ok "leak scan clean"
else bad "leak scan" "personal identifiers present; run build/leak-scan.py"; fi

printf "\n%s\n" "-----------------------------------------"
printf "verify: %s passed, %s failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && echo "RELEASABLE" || echo "NOT RELEASABLE"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
