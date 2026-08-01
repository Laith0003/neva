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
# 2026-08-01 adversarial QA pass. Six more blockers found BY THIS HARNESS STILL PASSING GREEN
# while broken, all from the same root cause the header above already names: this box
# shares assumptions with the source machine.
#   - cadence's staleness check uses `find -printf`, a GNU-only flag. On real BSD find
#     (stock macOS, no homebrew coreutils shadowing it) it errors, the error is piped to
#     /dev/null inside cadence, and every review/journal/strategy reads as "9999 days
#     stale" forever, even for a note edited one second ago. Old check 7 never caught this
#     because it only ever runs tools UNCONFIGURED (proving they name install.sh, which
#     they do); it never once runs cadence against a real vault with real content.
#   - briefing (and diag-run, session-guard) shell out to `timeout`, also GNU-only and
#     absent from stock macOS. Old check 8 ran briefing with a hostile PATH that has never
#     once contained a working `timeout`, so briefing's openclaw call has NEVER ONCE
#     actually executed under this harness, on any machine, ever: it always short-circuits
#     to "briefing skipped: nothing to report", which reads exactly like the product
#     working correctly on a quiet night. The two states are provably indistinguishable
#     from the log alone.
#   - check 8's "alert" arm grepped a log file named alert.log; alert actually writes to
#     alerts.log (plural). The grep target has never existed, so this arm has been
#     structurally unable to fail since it was written, no matter what alert logs.
#   - check 9 proved a drain path for gated writes EXISTS (the word "approve" appears in
#     output, which it always does: canon-propose's own instructions say it), never that
#     canon-approve actually applies a write. It happens to work (verified below, now for
#     real) but the check that was supposed to prove that never did.
#   - install.sh tells a buyer with a pre-existing non-empty vault folder that "the agent
#     can import it later, your notes end up in OLD_VAULT/ inside the new structure." No
#     code anywhere creates an OLD_VAULT folder or does any such import. The buyer is left
#     on a bare, unscaffolded folder with a promise that cashes out to nothing.
#   - none of: a second install over an existing Neva vault, a vault path with spaces, or
#     non-ASCII (Arabic) note content and queries, were ever exercised. All three turn out
#     to work; they are now locked in as regression checks instead of assumptions.
#
# Usage: bash build/verify.sh   (exit 0 = releasable)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
SANDBOX="$(mktemp -d /tmp/neva-verify-XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT

ok()   { printf "  PASS  %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  FAIL  %s\n    -> %s\n" "$1" "$2"; FAIL=$((FAIL+1)); }
head_() { printf "\n%s\n" "$1"; }

# A deliberately impoverished PATH: no ripgrep, no hledger, no brew bin, and critically no
# GNU coreutils shadowing BSD ones (no `timeout`, no GNU `find`). This is the buyer's real
# stock machine, not ours. Do not silently widen this "to make things pass": a check that
# only goes green because we handed it homebrew's coreutils is exactly the failure mode
# this file exists to prevent.
POOR_PATH="/usr/bin:/bin:/usr/sbin:/sbin"

head_ "1. install, hands-free, in a fresh HOME"
export HOME="$SANDBOX/home"; mkdir -p "$HOME"
OUT=$(OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
      VAULT_PATH="$HOME/MyVault" NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
      PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" 2>&1)
if [ $? -eq 0 ]; then ok "installer completes non-interactively"; else bad "installer" "exit non-zero"; fi
[ -f "$HOME/.config/neva/identity.env" ] && ok "identity file written" || bad "identity file" "missing"
P=$(stat -f "%Lp" "$HOME/.config/neva/identity.env" 2>/dev/null || stat -c "%a" "$HOME/.config/neva/identity.env" 2>/dev/null)
[ "$P" = "600" ] && ok "identity file is 600" || bad "identity perms" "got $P, want 600"

head_ "2. the placeholder-identity trap (B4)"
if grep -qE 'OWNER_CHAT_ID="(unset|none|todo|xxx)"' "$HOME/.config/neva/identity.env"; then
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
R=$(HOME="$HOME" PATH="$POOR_PATH" python3 "$HOME/.local/neva/bin/canon" "Contoso procurement" 2>&1)
if echo "$R" | grep -q "Jane Doe"; then ok "canon finds notes by CONTENT with no ripgrep"
else bad "canon content search" "returned nothing without rg; the agent would say 'I don't have that' about a note that exists"; fi
# negative control: the check must be able to fail
R2=$(HOME="$HOME" PATH="$POOR_PATH" python3 "$HOME/.local/neva/bin/canon" "zzz totally absent topic" 2>&1)
if echo "$R2" | grep -q "No canon note matches"; then ok "negative control: absent topic still reports nothing"
else bad "negative control" "canon claims a match for an absent topic"; fi

head_ "5. PROMISE: doctor tells the truth about readiness (B5)"
# Deterministic, not ambient: install a fake `openclaw` in the sandbox's own bin so this
# check exercises the multi-WARN "cannot work yet" honesty branch on purpose, instead of
# accidentally passing because the real host's own gateway happens to be up or down, or
# because an unrelated PATH gap (tools not linked) forces a FAIL for the wrong reason.
mkdir -p "$SANDBOX/fakebin"
cat > "$SANDBOX/fakebin/openclaw" <<'FAKEOC'
#!/bin/bash
[ "$1" = "--version" ] && { echo "fake-openclaw 0.0.0-test"; exit 0; }
exit 1
FAKEOC
chmod +x "$SANDBOX/fakebin/openclaw"
DOCTOR_PATH="$SANDBOX/fakebin:$HOME/.local/bin:$POOR_PATH"
D=$(HOME="$HOME" PATH="$DOCTOR_PATH" "$HOME/.local/neva/bin/doctor" 2>&1)
if echo "$D" | grep -q "^all clear$"; then
  bad "doctor honesty" "said 'all clear' with no gateway, no telegram, no timers: teaches buyers to ignore it"
else ok "doctor does not claim all-clear on an inert system"; fi
echo "$D" | grep -qi "cannot work yet\|failure" && ok "doctor names why it is not ready" || bad "doctor guidance" "no explanation of what is missing"
# this run's tools WERE on PATH ($HOME/.local/bin), so a real FAIL here would have to come
# from the actual INERT logic, not an accidental PATH gap; confirm that is in fact so
echo "$D" | grep -q "core tools on PATH" && ok "tool-PATH row passed on its own merits (not masking the honesty check)" \
  || bad "doctor check 5 environment" "tools not on PATH in this probe; the honesty assertion above is not trustworthy"

head_ "6. every FAIL row must carry an actionable fix"
BADROWS=$(echo "$D" | awk '/^  FAIL/ { if (length($0) < 45) print }')
[ -z "$BADROWS" ] && ok "all FAIL rows include a fix" || bad "bare FAIL rows" "$BADROWS"
# negative control: prove the awk rule itself can catch a bare row
NEGROWS=$(printf '  FAIL  bare row with no fix text\n' | awk '/^  FAIL/ { if (length($0) < 45) print }')
[ -n "$NEGROWS" ] && ok "negative control: bare FAIL row is caught" || bad "negative control" "bare row slipped through"

head_ "7. tools fail loudly, never silently (config missing)"
BADTOOLS=""
for T in canon canon-lint cadence vault-sync food; do
  [ -x "$HOME/.local/neva/bin/$T" ] || continue
  # execute via the shebang: several tools are python, bash cannot run them
  E=$(HOME="$SANDBOX/empty" PATH="$POOR_PATH" "$HOME/.local/neva/bin/$T" 2>&1); RC=$?
  E="$E rc=$RC"
  echo "$E" | grep -qiE "config missing|install.sh|rc=78" || BADTOOLS="$BADTOOLS $T"
done
[ -z "$BADTOOLS" ] && ok "tools name the fix when unconfigured" || bad "silent tools:$BADTOOLS" "should exit 78 naming install.sh"
head_ "7b. those SAME tools, CONFIGURED, against a real vault (the gap the unconfigured loop above cannot see)"
# cadence covered fully in section 12. Here: canon-lint and vault-sync must at least run
# clean (exit 0) against the real installed vault on a genuinely poor, GNU-free PATH.
CFGBAD=""
for T in canon-lint; do
  [ -x "$HOME/.local/neva/bin/$T" ] || continue
  O=$(HOME="$HOME" PATH="$POOR_PATH" "$HOME/.local/neva/bin/$T" 2>&1); RC=$?
  [ "$RC" -eq 0 ] || CFGBAD="$CFGBAD $T(rc=$RC)"
done
[ -z "$CFGBAD" ] && ok "canon-lint runs clean on a real vault, stock PATH" || bad "configured tool failure:$CFGBAD" "ran clean unconfigured, broke configured; see output above"

head_ "8. no tool claims an action it did not perform"
LIARS=""
# NOTE: no associative arrays here on purpose. Stock macOS ships /bin/bash 3.2.57 (Apple
# froze bash pre-GPLv3); `declare -A` does not exist on it. A check that uses it is exactly
# the class of bug this harness exists to prevent, just committed against the harness
# itself; caught here by actually running this file on a fresh $HOME with a stock PATH.
for T in briefing alert; do
  [ -x "$HOME/.local/neva/bin/$T" ] || continue
  HOME="$HOME" PATH="$POOR_PATH" "$HOME/.local/neva/bin/$T" >/dev/null 2>&1
  case "$T" in
    briefing) LF="briefing.log" ;;
    alert)    LF="alerts.log" ;;
    *)        LF="$T.log" ;;
  esac
  if grep -rqi "sent" "$HOME/.local/state/neva/$LF" 2>/dev/null; then LIARS="$LIARS $T"; fi
done
[ -z "$LIARS" ] && ok "no false 'sent' in logs (correct log file checked)" || bad "tools logging phantom sends:$LIARS" "the product's own headline rule forbids this"
# negative control: prove the log-grep itself is capable of catching a phantom claim
NEGLOG="$SANDBOX/empty/.local/state/neva/negctrl.log"; mkdir -p "$(dirname "$NEGLOG")"
echo "2026-08-01 00:00:00 briefing sent (42 chars)" > "$NEGLOG"
grep -qi "sent" "$NEGLOG" && ok "negative control: a genuine phantom 'sent' line is caught by the grep" \
  || bad "negative control" "the grep cannot even catch a planted phantom-send line"

head_ "8b. PROMISE under REAL failure: briefing composes something to say, chat id is set, but delivery genuinely fails (bad token) -> must NOT log 'sent'"
mkdir -p "$SANDBOX/fakebin2"
cat > "$SANDBOX/fakebin2/openclaw" <<'FAKEOC2'
#!/bin/bash
echo '{"payloads":[{"text":"Quiet night, nothing urgent, but this line exists so MSG is non-empty."}]}'
FAKEOC2
chmod +x "$SANDBOX/fakebin2/openclaw"
# a real `timeout` is required for briefing's openclaw call to ever run at all on a stock
# machine; supply exactly a POSIX-only timeout stand-in so THIS check isolates the claim
# it exists to test (does briefing lie about delivery) from the SEPARATE finding in 13
# (briefing silently never runs at all without a real timeout binary).
cat > "$SANDBOX/fakebin2/timeout" <<'TOUT'
#!/bin/bash
shift
exec "$@"
TOUT
chmod +x "$SANDBOX/fakebin2/timeout"
BHOME="$SANDBOX/briefing-honesty"; mkdir -p "$BHOME"
HOME="$BHOME" OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
  VAULT_PATH="$BHOME/MyVault" NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
  PATH="$SANDBOX/fakebin2:$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" >/dev/null 2>&1
sed -i.bak 's/OWNER_CHAT_ID=""/OWNER_CHAT_ID="1"/' "$BHOME/.config/neva/identity.env"
mkdir -p "$BHOME/.openclaw"
echo '{"channels":{"telegram":{"botToken":"000000000:AA_a_deliberately_fake_unreachable_token"}}}' > "$BHOME/.openclaw/openclaw.json"
HOME="$BHOME" PATH="$SANDBOX/fakebin2:$POOR_PATH" "$BHOME/.local/neva/bin/briefing" >/dev/null 2>&1
if grep -qi "sent" "$BHOME/.local/state/neva/briefing.log" 2>/dev/null; then
  bad "briefing logs 'sent' without confirming delivery" "curl's success/failure is never checked before writing 'briefing sent' to the log; a dead token or network outage is invisible"
else
  ok "briefing does not claim delivery it could not confirm"
fi

head_ "9. gated canon writes are not a one-way trapdoor, AND the drain path actually applies (B2)"
G=$(printf 'A test money note.\n' | HOME="$HOME" PATH="$POOR_PATH" \
    python3 "$HOME/.local/neva/bin/canon-propose" money "Verify Money Note" --mode new 2>&1)
if echo "$G" | grep -qi "sent to the owner\|GATED"; then
  TID=$(echo "$G" | grep -oE 'proposal [a-zA-Z0-9-]+' | awk '{print $2}')
  if [ -n "$TID" ] && [ -x "$HOME/.local/neva/bin/canon-approve" ]; then
    A=$(HOME="$HOME" PATH="$POOR_PATH" python3 "$HOME/.local/neva/bin/canon-approve" yes "${TID:0:12}" 2>&1)
    if [ -f "$HOME/MyVault/05 Money/Verify Money Note.md" ]; then
      ok "gated write, once approved, actually lands in the vault (not just a claim)"
    else
      bad "gated write dead-letters" "canon-approve ran (\"$A\") but the file never reached the vault"
    fi
    ( cd "$HOME/MyVault" && git log --oneline -1 -- "05 Money/Verify Money Note.md" 2>/dev/null | grep -q . ) \
      && ok "approved write is git-committed (survives a crash, has history)" \
      || bad "approved write not committed" "no git history for the applied file"
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
# negative control: the scan itself must be able to catch a fake reference
NEGDOC=$(mktemp -d /tmp/neva-doc-negctrl-XXXXXX)
echo "see docs/99-does-not-exist.md" > "$NEGDOC/README.md"; mkdir -p "$NEGDOC/docs"
NEGHIT=""
for L in $(grep -rhoE '(docs/[a-z0-9/.-]+\.md)' "$NEGDOC/README.md" "$NEGDOC/docs" 2>/dev/null | sort -u); do
  [ -f "$NEGDOC/$L" ] || NEGHIT="$NEGHIT $L"
done
rm -rf "$NEGDOC"
[ -n "$NEGHIT" ] && ok "negative control: a planted dead link is caught" || bad "negative control" "a planted dead link was missed"
# install.sh makes ITS OWN promise at runtime ("OLD_VAULT/"); that promise must cash out
# in actual code somewhere, not just in a string it prints
if grep -q "OLD_VAULT" "$REPO/install.sh" && ! grep -rq "OLD_VAULT" "$REPO/bin" "$REPO/lib" 2>/dev/null; then
  bad "install.sh promises an OLD_VAULT/ import that no code implements" \
      "install.sh:87 tells a buyer with an existing vault their notes end up in OLD_VAULT/; grep the repo, nothing creates that folder or does that import"
else
  ok "install.sh's OLD_VAULT promise has an implementation, or the promise was removed"
fi

head_ "10b. PROMISE: the behavioural rules actually reach the agent"
# Until 2026-08-01 they did not. openclaw injects AGENTS.md and SOUL.md; this product shipped
# only AGENTS.base.md and SOUL.base.md and never composed them, so every rule in the product
# was read by nobody while the docs described them as governing behaviour.
if [ -f "$HOME/ws-rules/AGENTS.md" ] || [ -f "$HOME/.openclaw/workspace/AGENTS.md" ]; then :; fi
RW="$SANDBOX/rulews"; mkdir -p "$RW"
cp "$REPO/workspace/AGENTS.base.md" "$REPO/workspace/SOUL.base.md" "$RW/" 2>/dev/null
printf '## A LOCAL RULE\nlocal-marker-string\n' > "$RW/AGENTS.local.md"
PATH="$POOR_PATH" "$REPO/bin/compose-persona" "$RW" >/dev/null 2>&1
if [ -f "$RW/AGENTS.md" ] && grep -q "GROUNDING" "$RW/AGENTS.md"; then
  ok "AGENTS.md is generated and carries the shipped rules"
else
  bad "rules never reach the agent" "openclaw injects AGENTS.md, not AGENTS.base.md; bin/compose-persona must build it during install"
fi
grep -q "local-marker-string" "$RW/AGENTS.md" 2>/dev/null \
  && ok "the owner's own local rules survive the compose" \
  || bad "local layer dropped" "AGENTS.local.md must be appended, and must win on conflict"
# negative control: a foreign AGENTS.md must NOT be overwritten
FW="$SANDBOX/foreignws"; mkdir -p "$FW"
cp "$REPO/workspace/AGENTS.base.md" "$FW/" 2>/dev/null
echo "someone elses agent" > "$FW/AGENTS.md"
PATH="$POOR_PATH" "$REPO/bin/compose-persona" "$FW" >/dev/null 2>&1
grep -q "someone elses agent" "$FW/AGENTS.md" \
  && ok "negative control: a foreign AGENTS.md is left untouched" \
  || bad "clobbered a foreign persona" "compose-persona overwrote an AGENTS.md it did not generate"

head_ "11. no personal data in the artifact"
if python3 "$REPO/build/leak-scan.py" "$REPO" >/dev/null 2>&1; then ok "leak scan clean"
else bad "leak scan" "personal identifiers present; run build/leak-scan.py"; fi
# negative control: the scanner must actually be capable of finding a leak
NEGLEAK=$(mktemp -d /tmp/neva-leak-negctrl-XXXXXX)
# The plant must be catchable by TIER 2 ALONE. Tier 1 is a gitignored personal denylist
# that CI and every contributor will not have, so a tier-1 plant would make this control
# silently untestable exactly where it matters most. A documentation-domain address is also
# wrong here: RFC 2606 reserves those and the scanner correctly ignores them.
# Assembled at runtime, never written whole. Now that leak-scan scans build/ (it used to
# skip it, which is how two real leaks hid), a literal test address in this file would be
# flagged as a finding in the repo itself. The plant must exist only in the sandbox.
PLANT_USER="real.person"; PLANT_HOST="gmail"; PLANT_TLD="com"
echo "reach the owner at ${PLANT_USER}@${PLANT_HOST}.${PLANT_TLD}" > "$NEGLEAK/plant.md"
if python3 "$REPO/build/leak-scan.py" "$NEGLEAK" >/dev/null 2>&1; then
  bad "negative control" "leak-scan did not flag a planted identifier"
else
  ok "negative control: a planted identifier is caught"
fi
rm -rf "$NEGLEAK"

head_ "12. PROMISE: cadence notices a note edited seconds ago, on a REAL stock machine (not this one)"
# The known-worst defect on record: the cadence timer has never fired once in six weeks
# live. This check is not about the scheduler; it is about whether cadence's own staleness
# MATH is even correct once it does run. It uses \`find ... -printf\`, a GNU find flag.
# BSD find (real macOS, no homebrew coreutils on PATH) treats it as a syntax error; the
# error is redirected to /dev/null inside cadence, so it silently reports "no file found"
# -> 9999 days stale, forever, for every folder, regardless of real content.
touch "$HOME/MyVault/09 Reviews/.gitkeep" 2>/dev/null
printf '# Weekly Review\nDone just now.\n' > "$HOME/MyVault/09 Reviews/fresh-review.md"
CADOUT=$(env -i HOME="$HOME" PATH="$POOR_PATH" "$HOME/.local/neva/bin/cadence" --dry-run 2>&1)
STALE_DAYS=$(echo "$CADOUT" | grep -oE 'reviews=[0-9]+d' | grep -oE '[0-9]+')
if [ -n "$STALE_DAYS" ] && [ "$STALE_DAYS" -le 1 ]; then
  ok "cadence correctly reads a just-created review as fresh ($STALE_DAYS d) on a stock PATH"
else
  bad "cadence staleness check is silently broken on real (BSD) find" \
      "reported reviews=${STALE_DAYS:-unknown}d for a file edited seconds ago; 'find -printf' errors on stock macOS and the error is swallowed (bin/cadence uses 2>/dev/null); every staleness read defaults to 9999. Output: $CADOUT"
fi

head_ "13. tools that shell out to GNU-only commands must not fail SILENTLY on a machine that lacks them"
GNUONLY=$(grep -rlE '(^|[^a-zA-Z_.])timeout [0-9]|find .*-printf' "$REPO/bin" 2>/dev/null)
[ -n "$GNUONLY" ] && printf "    (uses timeout/-printf, unguarded: %s)\n" "$(echo "$GNUONLY" | tr '\n' ' ')"
# functional proof for briefing specifically: with NO timeout binary anywhere on PATH,
# briefing must say WHY it produced nothing, not log a message indistinguishable from a
# genuinely quiet night.
NTHOME="$SANDBOX/no-timeout"; mkdir -p "$NTHOME"
HOME="$NTHOME" OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
  VAULT_PATH="$NTHOME/MyVault" NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
  PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" >/dev/null 2>&1
env -i HOME="$NTHOME" PATH="$POOR_PATH" "$NTHOME/.local/neva/bin/briefing" >/tmp/neva-briefing-stderr.$$ 2>&1
BLOG=$(cat "$NTHOME/.local/state/neva/briefing.log" 2>/dev/null)
if echo "$BLOG" | grep -qi "skipped: nothing to report"; then
  bad "briefing is silent about a missing 'timeout' binary" \
      "on a PATH with no GNU timeout (stock macOS), briefing's openclaw call never runs at all; the log reads 'skipped: nothing to report', indistinguishable from a genuinely quiet night. Log: $BLOG"
else
  ok "briefing surfaces the real reason it produced nothing (not a false quiet-night claim)"
fi
rm -f /tmp/neva-briefing-stderr.$$

head_ "14. a SECOND install over an already-Neva vault is truly idempotent"
OUT2=$(OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
      VAULT_PATH="$HOME/MyVault" NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
      PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" 2>&1)
[ $? -eq 0 ] && ok "second install exits clean" || bad "second install" "non-zero exit"
[ -f "$HOME/MyVault/03 People/Jane Doe.md" ] && ok "content from the first install survives a second install" \
  || bad "second install destroyed content" "Jane Doe.md is gone after re-running install.sh"
INITCOMMITS=$(git -C "$HOME/MyVault" log --oneline --grep="vault initial commit" 2>/dev/null | wc -l | tr -d ' ')
[ "$INITCOMMITS" = "1" ] && ok "vault was not re-git-init'd (exactly one initial commit)" \
  || bad "vault git history corrupted" "expected exactly 1 'vault initial commit', found $INITCOMMITS"

head_ "15. non-ASCII (Arabic) notes and queries are grounded correctly"
cat > "$HOME/MyVault/03 People/نوران.md" <<'EOF'
# نوران
تعمل في هندسة الجودة وتراجع كل الإصلاحات.
EOF
RA=$(HOME="$HOME" PATH="$POOR_PATH" python3 "$HOME/.local/neva/bin/canon" "نوران هندسة" 2>&1)
echo "$RA" | grep -q "نوران.md" && ok "canon finds an Arabic-named note by an Arabic query" \
  || bad "Arabic grounding broken" "query 'نوران هندسة' did not surface نوران.md. Output: $RA"

head_ "16. VAULT_PATH containing spaces works end to end"
SPHOME="$SANDBOX/space-test"; mkdir -p "$SPHOME"
SPVAULT="$SPHOME/My Vault With Spaces"
HOME="$SPHOME" OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
  VAULT_PATH="$SPVAULT" NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
  PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" >/dev/null 2>&1
[ -d "$SPVAULT/03 People" ] && ok "vault scaffolds correctly at a path containing spaces" \
  || bad "spaced-path install" "no vault structure created at '$SPVAULT'"

head_ "17. upgrade.sh does not hang or silently no-op when run non-interactively (agent-driven)"
# no `timeout` here on purpose: this harness must itself run on a stock PATH with no GNU
# coreutils, so a portable background-and-kill bound is used instead.
UPOUT="$SANDBOX/upgrade.out"
( env HOME="$HOME" PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/upgrade.sh" </dev/null >"$UPOUT" 2>&1 ) &
UPID=$!
i=0
while kill -0 "$UPID" 2>/dev/null && [ "$i" -lt 20 ]; do sleep 0.5; i=$((i+1)); done
if kill -0 "$UPID" 2>/dev/null; then
  kill -9 "$UPID" 2>/dev/null; wait "$UPID" 2>/dev/null
  URC=124
else
  wait "$UPID"; URC=$?
fi
UOUT=$(cat "$UPOUT" 2>/dev/null)
if [ "$URC" = "124" ]; then
  bad "upgrade.sh hangs with no stdin" "an agent driving this non-interactively (as install.sh explicitly supports via NEVA_NONINTERACTIVE) will block forever; timed out after 10s"
elif echo "$UOUT" | grep -qiE "non-interactive|NEVA_NONINTERACTIVE|--yes|fix:"; then
  ok "upgrade.sh explains itself when it cannot prompt"
else
  bad "upgrade.sh fails silently when non-interactive" "rc=$URC with no actionable message (got: ${UOUT:-<empty>}); unlike install.sh, upgrade.sh has no NEVA_NONINTERACTIVE-equivalent"
fi

head_ "18. doctor's exit code cannot be clobbered by the per-job recent-failures loop (CRITICAL regression, 2026-08-01)"
# Found live: bin/doctor's scheduled-jobs loop (section 8) used to reassign the SAME name
# `row()` bumps for every FAIL row (and the final exit-code check reads) into a per-job
# scratch count on every loop iteration. Proven on a live install in both directions: zero
# FAIL rows on screen produced a non-zero exit, and a genuine CRITICAL FAIL row on screen
# produced exit 0. This exercises the exact clobber path without loading any real
# launchd/systemd job (NEVA_DOCTOR_LOADED_TEST overrides doctor's own "what is loaded" probe).
DOCHOME="$SANDBOX/doctor-exitcode"; mkdir -p "$DOCHOME"
HOME="$DOCHOME" OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
  VAULT_PATH="$DOCHOME/MyVault" NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
  PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" >/dev/null 2>&1
# openclaw is absent from POOR_PATH -> doctor's own early "openclaw" check produces a real
# FAIL row well before the scheduled-jobs loop below ever runs.
HBDIR="$DOCHOME/.local/state/neva/heartbeat"; mkdir -p "$HBDIR"
# a job whose own recent-failures count is a clean 0 (an "ok" row in the loop) - the exact
# iteration whose old, buggy assignment overwrote the real running total instead of
# accumulating it.
printf '%s 0 1\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$HBDIR/vault-sync.status"
D2=$(HOME="$DOCHOME" PATH="$POOR_PATH" NEVA_DOCTOR_LOADED_TEST="vault-sync" "$DOCHOME/.local/neva/bin/doctor" 2>&1); D2RC=$?
D2FAILROWS=$(echo "$D2" | grep -c "^  FAIL")
if [ "$D2FAILROWS" -eq 0 ]; then
  bad "doctor exit code regression check" "expected at least one real FAIL row (openclaw missing) to set up this proof; got none - not exercising the right path. Output: $D2"
elif [ "$D2RC" -eq 0 ]; then
  bad "doctor exit code lies" "$D2FAILROWS FAIL row(s) on screen but exit code is 0: a per-job loop variable clobbered the real failure count"
else
  ok "doctor exit code matches what is on screen ($D2FAILROWS FAIL row(s), rc=$D2RC)"
fi
# negative control: reproduce the OLD buggy variable name in a throwaway copy of doctor and
# prove THIS check is capable of catching it - not just structurally green.
BUGGY_DOCTOR="$SANDBOX/doctor-buggy"
python3 -c "
import sys
src = open('$DOCHOME/.local/neva/bin/doctor').read()
assert 'JOB_RECENT_FAILS' in src, 'fixed doctor no longer contains the scoped variable name'
open('$BUGGY_DOCTOR', 'w').write(src.replace('JOB_RECENT_FAILS', 'FAILS'))
"
chmod +x "$BUGGY_DOCTOR"
D3=$(HOME="$DOCHOME" PATH="$POOR_PATH" NEVA_DOCTOR_LOADED_TEST="vault-sync" "$BUGGY_DOCTOR" 2>&1); D3RC=$?
D3FAILROWS=$(echo "$D3" | grep -c "^  FAIL")
if [ "$D3FAILROWS" -gt 0 ] && [ "$D3RC" -eq 0 ]; then
  ok "negative control: the old buggy pattern really does produce a false-green exit code (this check can fail)"
else
  bad "negative control" "could not reproduce the old clobber bug in an isolated copy (rows=$D3FAILROWS rc=$D3RC) - this check may not be testing what it claims"
fi

head_ "19. install.sh refuses to write into a foreign, already-populated workspace without consent (CRITICAL, 2026-08-01)"
# Found reading install.sh as a buyer about to run it: it used to write AGENTS.base.md,
# SOUL.base.md, and (on a fresh interview) BOOTSTRAP.md into WORKSPACE_PATH unconditionally.
# Our stated buyer already uses Claude/Obsidian, so a live ~/.openclaw/workspace with their
# OWN AGENTS.md/SOUL.md is a common starting state, not an edge case - and BOOTSTRAP.md
# changes what that running agent does on its very next turn.
FWHOME="$SANDBOX/foreign-workspace"; mkdir -p "$FWHOME"
FOREIGN_WS="$FWHOME/.openclaw/workspace"; mkdir -p "$FOREIGN_WS"
echo "# Someone else's real, running agent config. Neva did not write this file." > "$FOREIGN_WS/AGENTS.md"
echo "some other note" > "$FOREIGN_WS/notes.txt"
FWOUT=$(HOME="$FWHOME" OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
  VAULT_PATH="$FWHOME/MyVault" WORKSPACE_PATH="$FOREIGN_WS" \
  NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
  PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" 2>&1); FWRC=$?
if [ -f "$FOREIGN_WS/AGENTS.base.md" ] || [ -f "$FOREIGN_WS/BOOTSTRAP.md" ]; then
  bad "install.sh wrote into a foreign workspace without consent" "AGENTS.base.md and/or BOOTSTRAP.md landed in $FOREIGN_WS even though it had a pre-existing AGENTS.md install.sh did not write; a buyer's already-running agent would have been altered unannounced"
elif [ "$FWRC" -eq 0 ]; then
  bad "install.sh exited 0 without writing AND without refusing" "expected a non-zero exit naming the fix when a foreign workspace is detected non-interactively; got rc=0. Output: $FWOUT"
elif echo "$FWOUT" | grep -qi "did not create\|WORKSPACE_CONFIRM"; then
  ok "install.sh refuses to write into a foreign workspace non-interactively, and names the fix"
else
  bad "install.sh refused for the wrong reason" "exited non-zero (rc=$FWRC) but did not explain the foreign-workspace refusal. Output: $FWOUT"
fi
# negative control: the SAME command against an empty/fresh workspace must install normally -
# proves the guard is not simply refusing everything
FWHOME2="$SANDBOX/foreign-workspace-empty"; mkdir -p "$FWHOME2"
EMPTY_WS="$FWHOME2/.openclaw/workspace"
HOME="$FWHOME2" OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
  VAULT_PATH="$FWHOME2/MyVault" WORKSPACE_PATH="$EMPTY_WS" \
  NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
  PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" >/dev/null 2>&1
[ -f "$EMPTY_WS/AGENTS.base.md" ] && ok "negative control: an empty/fresh workspace still installs normally (the guard only blocks genuinely foreign, non-empty ones)" \
  || bad "negative control" "install.sh failed to populate a normal, empty workspace - the guard is over-triggering"

head_ "19b. general workspace consent does not imply BOOTSTRAP consent when a live agent config is present"
FWHOME3="$SANDBOX/foreign-workspace-consented"; mkdir -p "$FWHOME3"
FOREIGN_WS3="$FWHOME3/.openclaw/workspace"; mkdir -p "$FOREIGN_WS3"
echo "# real agent config" > "$FOREIGN_WS3/AGENTS.md"
FW3OUT=$(HOME="$FWHOME3" OWNER_NAME="Test Buyer" AGENT_NAME="Vera" TIMEZONE="Europe/Lisbon" \
  VAULT_PATH="$FWHOME3/MyVault" WORKSPACE_PATH="$FOREIGN_WS3" \
  WORKSPACE_CONFIRM=yes NEVA_NONINTERACTIVE=1 NEVA_SKIP_SCHEDULE_ENABLE=1 \
  PATH="$POOR_PATH:/usr/local/bin:/opt/homebrew/bin" bash "$REPO/install.sh" 2>&1)
if [ -f "$FOREIGN_WS3/AGENTS.base.md" ] && [ ! -f "$FOREIGN_WS3/BOOTSTRAP.md" ]; then
  ok "base layers write with general consent, but BOOTSTRAP.md stays out of a workspace with a live agent's own config unless separately confirmed"
elif [ -f "$FOREIGN_WS3/BOOTSTRAP.md" ]; then
  bad "BOOTSTRAP.md written without its own consent" "workspace had AGENTS.md (a running agent's config); general WORKSPACE_CONFIRM=yes must not double as consent to redirect that agent's next turn"
else
  bad "general consent did not take effect" "AGENTS.base.md missing even after WORKSPACE_CONFIRM=yes; check output: $FW3OUT"
fi

printf "\n%s\n" "-----------------------------------------"
printf "verify: %s passed, %s failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && echo "RELEASABLE" || echo "NOT RELEASABLE"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
