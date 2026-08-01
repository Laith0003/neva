## What this does
One sentence: what changed and why.

## Type of change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Performance improvement
- [ ] Other: (describe)

## Before you open this PR

Make sure you have:

- [ ] Run `bash build/verify.sh` and it passes (exit 0, "33 passed, 0 failed, RELEASABLE")
- [ ] Run `python3 build/leak-scan.py .` and it exits 0 (no identifiers leaked)
- [ ] Signed your commit with `git commit -s` (DCO sign-off)
- [ ] Tested your change on the platform you are submitting from (macOS or Linux)

If your PR adds a new feature or a new promise in the README, add a check to `build/verify.sh`
that proves it, and prove the check can fail by temporarily breaking the thing and verifying
the check goes red.

A check that always passes is worse than no check; four of those have shipped here and hid
real bugs.

## Testing
- [ ] This change was tested on macOS / Linux (circle one, or both)
- [ ] If this adds new behavior, it is covered by a verify.sh check that can fail
- [ ] If this touches Telegram, install.sh, or scheduled jobs, it was tested end-to-end

## Documentation
- [ ] README.md is still accurate
- [ ] If this changes a feature, the relevant docs/XX.md file is updated
- [ ] If this adds a feature, relevant docs exist or are noted as TBD

## No emojis, no em-dashes
- [ ] Commit message has no emojis and no em-dashes (`--` or "phrase — phrase")
- [ ] Code comments, docstrings, and error messages follow the same rule

---

(Delete this entire template from your message; GitHub will fill the PR title and body.)
