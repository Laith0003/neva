---
name: Broken install
about: install.sh or the setup interview did not complete
title: ''
labels: bug, install
assignees: ''

---

## What happened
install.sh exited with an error, or the setup interview could not complete, or something else
during initial setup broke and the product is not yet working.

## When
- First time installing, or upgrading from version: (date or version number)
- Installation method: (manual `install.sh` or agent setup via START.md)
- OS: (output of `uname -a`)

## The failure
Paste the full output of the install attempt:

```
(full output, including all errors)
```

Also run and paste:

```
doctor
```

And (if you cloned the repo locally):

```
bash build/verify.sh
```

## What worked before it broke
Did you get partway through install? For example:
- openclaw installed but then install.sh failed
- identity.env was created but the vault was not
- the interview ran but Telegram setup failed
- etc.

Include whatever got created before things stopped.

## Your environment
- macOS version or Linux distribution: (e.g., macOS 14.6, Ubuntu 24.04)
- Shell you are using: (bash, zsh, fish)
- Any non-standard setup: (non-English locale, sandboxed shell, unusual PATH)
