#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Thin shim onto the one instinct engine: skills/continuous-learning-v2/scripts/.

  instincts.py [--cwd DIR] analyze [instinct-analyze.py flags]   the nightly job, now
  instincts.py [--cwd DIR] <instinct-cli.py command> [args]      everything else

It only fills in what the engine cannot find on its own from a hook context: NEVA_VAULT (from
VAULT_PATH in the identity file when unset) and the project directory (--cwd becomes
CLAUDE_PROJECT_DIR and the working directory). All behavior, layout and output belong to the
engine; see skills/continuous-learning-v2/SKILL.md.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from neva_hooks import common as c  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "continuous-learning-v2", "scripts")


def main(argv):
    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if len(argv) >= 2 and argv[0] == "--cwd":
        cwd, argv = argv[1], argv[2:]
    if not argv:
        sys.stderr.write("usage: instincts.py [--cwd DIR] <analyze | status | search | propose | apply-promotions | "
                         "...>\nFix: pass a command; `instincts.py --help` lists the engine's commands.\n")
        return 64
    script = "instinct-analyze.py" if argv[0] == "analyze" else "instinct-cli.py"
    args = argv[1:] if argv[0] == "analyze" else argv
    target = os.path.join(SCRIPTS, script)
    if not os.path.exists(target):
        sys.stderr.write(f"{target} is missing. Fix: reinstall the neva-core plugin; the hooks folder and "
                         "skills/continuous-learning-v2 ship together.\n")
        return 2
    env = dict(os.environ, CLAUDE_PROJECT_DIR=os.path.realpath(cwd))
    if not env.get("NEVA_VAULT"):
        vault = c.vault_path()
        if vault:
            env["NEVA_VAULT"] = vault
    return subprocess.call([sys.executable, target, *args], cwd=cwd, env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
