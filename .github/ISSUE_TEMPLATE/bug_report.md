---
name: Bug report
about: Something is broken; doctor or verify.sh can help diagnose it
title: ''
labels: bug
assignees: ''

---

## Summary
One sentence: what does not work.

## Steps to reproduce
1. Ran: (your command)
2. Expected: (what should happen)
3. Got: (what actually happened)

## Environment
- OS: (output of `uname -a`)
- Neva install path: (output of `pwd` when you run install.sh, or git clone path)
- Installation method: (manual `install.sh` or agent setup)

## Diagnosis
Run these and paste the output:

```
doctor
```

```
bash build/verify.sh
```

If you cloned the repo and want to help us debug faster, also run:
```
python3 build/leak-scan.py .
```

(This checks if any personal identifiers accidentally ended up in files; exit 0 means clean.)

## Error output
If the command printed an error, paste the full output here (no need to redact, we are not
looking at credentials, just the error):

```
(full error or terminal output)
```

## Additional context
Anything else that might help us reproduce it on a similar machine, such as:
- First time running this (vs. an upgrade)
- Non-standard vault path or workspace path
- Unusual shell or PATH
- Any integrations you have enabled (hledger, syncthing, etc.)
