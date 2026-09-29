# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Shared fixtures for the neva-core script tests. Standard library only.

Every test gets a temp HOME and a scrubbed environment so nothing on the machine running the
tests (real plugins, real transcripts, real vault, real gh auth) can leak in or be touched.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
PLUGIN = os.path.dirname(SCRIPTS)
PY = sys.executable

SCRUB = ("NEVA_", "XDG_", "CLAUDE_", "GH_", "GITHUB_", "AUDIT_ROOT")

FAKE_GH = r'''#!__PY__
"""Fake gh: issue view/list/edit/comment against a JSON state file. Logs every call."""
import json, os, sys
state_path = os.environ["FAKE_GH_STATE"]
log_path = os.environ["FAKE_GH_LOG"]
args = sys.argv[1:]
with open(log_path, "a") as fh:
    fh.write(json.dumps(args) + "\n")
with open(state_path) as fh:
    state = json.load(fh)

def opt(name, many=False):
    vals, i = [], 0
    while i < len(args):
        if args[i] == name and i + 1 < len(args):
            vals.append(args[i + 1]); i += 2; continue
        i += 1
    return vals if many else (vals[-1] if vals else None)

def view(issue):
    out = dict(issue)
    out["labels"] = [{"name": n} for n in issue.get("labels", [])]
    out["author"] = {"login": issue.get("author", "octo")}
    out.setdefault("url", "https://github.com/%s/issues/%s" % (state["repo"], issue["number"]))
    out.setdefault("updatedAt", "2026-09-01T00:00:00Z")
    out.setdefault("assignees", [])
    out.pop("comments", None)
    return out

def find(n):
    for i in state["issues"]:
        if str(i["number"]) == str(n):
            return i
    sys.stderr.write("GraphQL: Could not resolve to an issue with the number of %s.\n" % n)
    sys.exit(1)

sub = args[:2]
fail = os.environ.get("FAKE_GH_FAIL_ON", "")
if fail and fail == args[1]:
    sys.stderr.write("HTTP 502: fake failure on %s\n" % fail)
    sys.exit(1)
if opt("--repo") != state["repo"]:
    sys.stderr.write("HTTP 404: repo %s not found\n" % opt("--repo")); sys.exit(1)
if sub == ["issue", "view"]:
    print(json.dumps(view(find(args[2]))))
elif sub == ["issue", "list"]:
    st, label, search = opt("--state") or "open", opt("--label"), opt("--search")
    rows = []
    for i in state["issues"]:
        if st != "all" and i.get("state", "OPEN").lower() != st:
            continue
        if label and label not in i.get("labels", []):
            continue
        if search:
            needle = search.split('"')[1] if '"' in search else search
            if needle not in (i.get("body") or ""):
                continue
        rows.append(view(i))
    print(json.dumps(rows[: int(opt("--limit") or 30)]))
elif sub == ["issue", "edit"]:
    i = find(args[2])
    body = opt("--body")
    if body is not None:
        i["body"] = body
    labels = set(i.get("labels", []))
    labels |= set(opt("--add-label", True))
    labels -= set(opt("--remove-label", True))
    i["labels"] = sorted(labels)
    print("https://github.com/%s/issues/%s" % (state["repo"], i["number"]))
elif sub == ["issue", "comment"]:
    i = find(args[2])
    i.setdefault("comments", []).append(opt("--body"))
    print("https://github.com/%s/issues/%s#issuecomment-1" % (state["repo"], i["number"]))
else:
    sys.stderr.write("fake gh: unsupported %r\n" % args); sys.exit(1)
with open(state_path, "w") as fh:
    json.dump(state, fh, indent=2)
'''

FAKE_TMUX = r'''#!__PY__
"""Fake tmux: logs calls; split-window -P prints a pane id; has-session fails unless a
session file exists; FAKE_TMUX_FAIL_ON=<subcommand> makes that subcommand fail."""
import json, os, sys
args = sys.argv[1:]
log = os.environ["FAKE_TMUX_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_TMUX_FAIL_ON") and args and args[0] == os.environ["FAKE_TMUX_FAIL_ON"]:
    sys.stderr.write("fake tmux failure\n"); sys.exit(1)
sessions = os.environ["FAKE_TMUX_SESSIONS"]
if args[:1] == ["-V"]:
    print("tmux 3.4")
elif args[:1] == ["has-session"]:
    sys.exit(0 if os.path.exists(os.path.join(sessions, args[2])) else 1)
elif args[:1] == ["new-session"]:
    open(os.path.join(sessions, args[args.index("-s") + 1]), "w").close()
elif args[:1] == ["kill-session"]:
    p = os.path.join(sessions, args[2])
    if os.path.exists(p):
        os.remove(p)
elif args[:1] == ["split-window"]:
    n = sum(1 for _ in open(log))
    print("%%%d" % n)
'''


def clean_env(home, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB)}
    env["HOME"] = home
    env["GIT_CONFIG_GLOBAL"] = os.path.join(home, ".gitconfig")
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "test@example.invalid"
    env.update(extra or {})
    return env


def write_exe(path, source):
    with open(path, "w") as fh:
        fh.write(source.replace("__PY__", PY))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Sandbox:
    def __init__(self, prefix):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        self.work = os.path.join(self.tmp, "work")
        for d in (self.home, self.bin, self.work):
            os.makedirs(d)
        self.env = clean_env(self.home, {"PATH": self.bin + os.pathsep + os.environ.get("PATH", "")})

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def write(self, rel, content):
        p = rel if os.path.isabs(rel) else self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content if isinstance(content, str) else json.dumps(content, indent=2))
        return p

    def run(self, script, *args, cwd=None, stdin=None, env=None):
        e = dict(self.env)
        e.update(env or {})
        return subprocess.run([PY, os.path.join(SCRIPTS, script)] + list(args), cwd=cwd or self.work, env=e,
                              capture_output=True, text=True, input=stdin, timeout=60)

    def git(self, *args, cwd=None):
        r = subprocess.run(["git"] + list(args), cwd=cwd or self.work, env=self.env, capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
        return r.stdout
