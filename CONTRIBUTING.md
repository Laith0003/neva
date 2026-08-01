# Contributing

Contributions are wanted, including ones that change how this works rather than just
fixing it.

## Sign your commits

Use `git commit -s`. That appends a `Signed-off-by:` line, which is your agreement to the
Developer Certificate of Origin (DCO) at https://developercertificate.org: that you wrote
the change, or have the right to submit it, and that it may ship under this project's licence,
including the commercial terms the author sells under.

That single line is the whole legal process. There is no CLA and no form. It exists so the
project can be sold, given away, or relicensed later without having to track down every
past contributor for permission.

## Before you open a pull request

Run the harness:

    bash build/verify.sh

It installs the product from scratch in a throwaway sandbox with a deliberately stripped
PATH, then asserts the outcomes a buyer would notice. It must read `33 passed, 0 failed,
RELEASABLE`. If your change adds a promise, add the check that proves it, and prove the
check can fail by breaking the thing on purpose and watching it go red. A check that
cannot fail is worse than no check: four of those shipped here once and hid five real bugs.

Also run:

    python3 build/leak-scan.py .

Exit 1 means it found an identifier that must not ship. It blocks commits on purpose.

## House rules, enforced in review

- No emojis anywhere: code, comments, docs, commit messages, UI. Inline SVG or plain text.
- No em-dashes, and no `--`, in prose.
- Errors name the field AND the fix. Never "something went wrong".
- No tool may claim an action it did not perform. If a send fails, the log says so.
- Never print a credential, not even partially, not even to confirm it.

## What gets a fast yes

Bug fixes with a failing test first. Support for a platform you actually ran it on. Docs
that correct something untrue. Removing a feature that does not work.

## What gets pushback

A promise in the README with no code behind it. A new dependency that is not a single
binary or pure Python. Anything requiring Docker. A check that passes without asserting
anything.
