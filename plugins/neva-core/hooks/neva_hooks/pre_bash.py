# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""PreToolUse (Bash): git hook-bypass block, commit quality, push reminder, dev server in tmux.

Module ids (see hooks.meta.json): no_verify, commit_quality, push_reminder, tmux_dev.
Commands are parsed quote-aware, so a flag that only appears inside a commit message
(`git commit -m "never use --no-verify"`) is not mistaken for the real flag.
"""
import os
import re
import shlex

from . import common as c

SEPARATORS = {";", "&&", "||", "|", "&", ";;", "|&", "(", ")"}
WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "nice", "builtin"}
NO_VERIFY_CMDS = {"commit", "push", "merge", "cherry-pick", "rebase", "am"}
COMMIT_VALUE_OPTS = {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message",
                     "--author", "--date", "--template", "-t", "--fixup", "--squash", "--pathspec-from-file",
                     "--cleanup", "--trailer"}
GIT_GLOBAL_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                         "--config-env", "--exec-path"}


# ---------------------------------------------------------------- parsing

def _newlines_to_semicolons(cmd):
    out, quote, i = [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(cmd):
                out.append(cmd[i:i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "\\" and i + 1 < len(cmd):
            out.append(cmd[i:i + 2])
            i += 2
            continue
        elif ch == "\n":
            ch = ";"
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_heredocs(cmd):
    return re.sub(r"<<-?\s*['\"]?(\w+)['\"]?\n.*?\n\s*\1\b", "<<HEREDOC", cmd, flags=re.S)


def segments(cmd):
    """List of token lists, one per simple command. None when the line cannot be parsed."""
    try:
        lex = shlex.shlex(_newlines_to_semicolons(_strip_heredocs(cmd)), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        toks = list(lex)
    except ValueError:
        return None
    segs, cur = [], []
    for t in toks:
        if t in SEPARATORS or (t and set(t) <= set(";&|()")):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def unwrap(tokens):
    """Skip env assignments and wrapper commands. Returns (index of command word, env dict)."""
    envs, i = {}, 0
    while i < len(tokens):
        t = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            k, v = t.split("=", 1)
            envs[k] = v
            i += 1
            continue
        base = os.path.basename(t)
        if base in WRAPPERS:
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
            continue
        break
    return i, envs


def git_call(tokens):
    """(subcommand, rest, global_config_values, envs) for a git segment, else None."""
    i, envs = unwrap(tokens)
    if i >= len(tokens) or os.path.basename(tokens[i]).lower() not in ("git", "git.exe"):
        return None
    configs, j = [], i + 1
    while j < len(tokens):
        t = tokens[j]
        if t in GIT_GLOBAL_VALUE_OPTS:
            if t == "-c" and j + 1 < len(tokens):
                configs.append(tokens[j + 1])
            j += 2
            continue
        if t.startswith("-c") and len(t) > 2:
            configs.append(t[2:])
            j += 1
            continue
        if t.startswith("-"):
            j += 1
            continue
        return t.lower(), tokens[j + 1:], configs, envs
    return None


def short_cluster(tok):
    """Parse a commit short-option cluster like -am or -nm. Returns (flags before any value,
    whether the next token is consumed as a value)."""
    flags = set()
    body = tok[1:]
    for k, ch in enumerate(body):
        if ch in "mFCct":
            return flags, k == len(body) - 1  # value attached, or the next token is the value
        if ch in "uS":
            return flags, False  # optional attached value swallows the rest
        flags.add(ch)
    return flags, False


def bypass_reason(cmd):
    segs = segments(cmd)
    if segs is None:
        if re.search(r"\bgit\b.*\s--no-verify\b", cmd):
            return "git ... --no-verify"
        return None
    for toks in segs:
        g = git_call(toks)
        if not g:
            continue
        sub, rest, configs, envs = g
        if envs.get("HUSKY") == "0":
            return f"HUSKY=0 git {sub}"
        for cv in configs:
            if cv.lower().startswith("core.hookspath"):
                return f"git -c {cv} {sub}"
        if sub == "config":
            args = [a for a in rest if not a.startswith("-")]
            if args and args[0].lower() == "core.hookspath" and len(args) > 1:
                return "git config core.hooksPath"
        if sub not in NO_VERIFY_CMDS:
            continue
        k = 0
        while k < len(rest):
            t = rest[k]
            if t == "--":
                break
            if t.startswith("--") and "=" not in t and len(t) >= len("--no-v") and "--no-verify".startswith(t):
                return f"git {sub} {t}"
            if sub == "commit":
                if t in COMMIT_VALUE_OPTS:
                    k += 2
                    continue
                if t.startswith("-") and not t.startswith("--") and len(t) > 1:
                    flags, eats_next = short_cluster(t)
                    if "n" in flags:
                        return f"git commit {t} (-n is --no-verify)"
                    if eats_next:
                        k += 2
                        continue
            k += 1
    return None


# ---------------------------------------------------------------- no_verify

def no_verify(ctx):
    if ctx.tool_name != "Bash":
        return None
    cmd = str(ctx.tool_input.get("command") or "")
    if "git" not in cmd and "HUSKY" not in cmd:
        return None
    why = bypass_reason(cmd)
    if not why:
        return None
    return {"block": (f"Blocked: `{why}` skips the repository's git hooks. Run the failing hook directly to see "
                      "its error and fix the cause, or ask the user to run the command themselves if skipping "
                      "is intended.")}


# ---------------------------------------------------------------- commit_quality

CONVENTIONAL = re.compile(r"^(feat|fix|docs|style|refactor|test|chore|build|ci|perf|revert)(\([^)]+\))?!?: .+")
CODE_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".py", ".rb", ".php", ".go", ".rs")
PLACEHOLDER = re.compile(r"^(|process\.env\.\w+|\$\{[^}]*\}|<[^<>]*>|(replace_?me|change_?me|your[_-]?\w*|x{3,}|"
                         r"todo|tbd|fixme|dummy|example|test|changeit|placeholder)\w*)$", re.I)
GENERIC_SECRET = re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*['\"]([^'\"]{12,})['\"]")


def commit_message(cmd, tokens):
    heredoc = re.search(r"<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\s*\1\b", cmd, re.S)
    msgs, k = [], 0
    while k < len(tokens):
        t = tokens[k]
        if (t == "--message" or re.match(r"^-[a-zA-Z]*m$", t)) and k + 1 < len(tokens):
            msgs.append(tokens[k + 1])
            k += 2
            continue
        if t.startswith("--message="):
            msgs.append(t.split("=", 1)[1])
        elif t.startswith("-m") and len(t) > 2 and not t.startswith("--"):
            msgs.append(t[2:])
        k += 1
    if not msgs:
        return None
    first = msgs[0]
    if "$(" in first and heredoc:
        first = heredoc.group(2)
    return first.strip().splitlines()[0].strip() if first.strip() else ""


def message_warnings(subject):
    warns = []
    if subject is None:
        return warns
    if not CONVENTIONAL.match(subject):
        warns.append('message is not conventional: use "type(scope): summary", e.g. "fix(auth): expire stale tokens"')
    if len(subject) > 72:
        warns.append(f"subject is {len(subject)} characters: keep it at 72 or fewer")
    if subject.endswith("."):
        warns.append("subject ends with a period: drop it")
    m = CONVENTIONAL.match(subject)
    if m and re.match(r"^[A-Z]", subject.split(":", 1)[1].strip()):
        warns.append("summary after the type starts uppercase: use lowercase")
    return warns


def scan_added_lines(diff_text):
    """(errors, warnings) as lists of 'file:line: what' strings from a unified diff."""
    errors, warns = [], []
    fname, lineno = "", 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            fname = raw[4:].strip()
            fname = fname[2:] if fname.startswith("b/") else fname
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", raw)
        if m:
            lineno = int(m.group(1))
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        line = raw[1:]
        where = f"{fname}:{lineno}"
        lineno += 1
        for rx, label in c.SECRET_SHAPES:
            if rx.search(line):
                errors.append(f"{where}: {label}")
                break
        else:
            g = GENERIC_SECRET.search(line)
            if g and not PLACEHOLDER.match(g.group(2).strip()):
                warns.append(f"{where}: possible hardcoded {g.group(1).lower()}")
        if not fname.endswith(CODE_EXT):
            continue
        s = line.strip()
        if s.startswith(("//", "#", "*", "/*")):
            continue
        if re.search(r"\bdebugger\b", s) and fname.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")):
            errors.append(f"{where}: debugger statement")
        elif re.search(r"\b(breakpoint\(\)|pdb\.set_trace\(\))", s) and fname.endswith(".py"):
            errors.append(f"{where}: debugger breakpoint")
        elif re.search(r"\bbinding\.pry\b", s) and fname.endswith(".rb"):
            errors.append(f"{where}: debugger breakpoint")
        elif "console.log" in s:
            warns.append(f"{where}: console.log")
    return errors, warns


def commit_quality(ctx):
    if ctx.tool_name != "Bash":
        return None
    cmd = str(ctx.tool_input.get("command") or "")
    if "commit" not in cmd:
        return None
    segs = segments(cmd) or []
    for toks in segs:
        g = git_call(toks)
        if not g or g[0] != "commit" or "--amend" in g[1]:
            continue
        rest = g[1]
        warns = [f"commit message: {w}" for w in message_warnings(commit_message(cmd, rest))]
        all_flag = any(t == "--all" or (re.match(r"^-[a-zA-Z]+$", t) and "a" in short_cluster(t)[0])
                       for t in rest)
        diff_args = ["diff", "--unified=0", "--no-color", "--diff-filter=ACMR"]
        diff = c.git(diff_args + (["HEAD"] if all_flag else ["--cached"]), ctx.cwd, timeout=5) or ""
        errors, dwarns = scan_added_lines(diff)
        warns += dwarns
        if errors:
            shown = "\n".join(f"  {e}" for e in errors[:10])
            more = f"\n  ... and {len(errors) - 10} more" if len(errors) > 10 else ""
            return {"block": ("Blocked: the staged changes contain:\n" + shown + more + "\nRemove each one "
                              "(load secrets from the environment and rotate any key that was real, delete "
                              "debugger statements), re-stage, then commit.")}
        if warns:
            return {"context": "Commit check warnings (not blocking):\n" + "\n".join(f"- {w}" for w in warns[:12])}
    return None


# ---------------------------------------------------------------- push_reminder

def push_reminder(ctx):
    if ctx.tool_name != "Bash":
        return None
    cmd = str(ctx.tool_input.get("command") or "")
    if "push" not in cmd:
        return None
    for toks in segments(cmd) or []:
        g = git_call(toks)
        if g and g[0] == "push":
            rest = g[1]
            forced = any(t in ("-f", "--force") or t.startswith("--force-with-lease") or t.startswith("+")
                         for t in rest)
            shared = any(re.search(r"(^|:|/)(main|master|trunk|develop)$", t.lstrip("+")) for t in rest
                         if not t.startswith("-"))
            msg = ("Before this push: `git status` should be clean and `git log @{u}..HEAD` should list only the "
                   "commits meant for the remote.")
            if shared:
                msg += " This targets a shared branch: pushing there needs the user's explicit OK for this push."
            if forced:
                msg += " It is a force push: it rewrites remote history others may have pulled."
            return {"context": msg}
    return None


# ---------------------------------------------------------------- tmux_dev

DEV_SERVER = re.compile(
    r"\b(npm\s+run\s+(dev|start|serve)|pnpm(\s+run)?\s+(dev|start)|yarn(\s+run)?\s+(dev|start)|bun(\s+run)?\s+dev|"
    r"next\s+dev|vite(\s+dev)?\s*$|php\s+artisan\s+serve|manage\.py\s+runserver|rails\s+s(erver)?\b|"
    r"flask\s+run|uvicorn\s|hugo\s+server|astro\s+dev)"
)


def tmux_dev(ctx):
    if ctx.tool_name != "Bash":
        return None
    cmd = str(ctx.tool_input.get("command") or "")
    if not DEV_SERVER.search(cmd):
        return None
    if c.env("TMUX") or ctx.tool_input.get("run_in_background") is True:
        return None
    if re.match(r"^\s*tmux\s+(new|new-session|new-window|split-window)\b", cmd):
        return None
    name = re.sub(r"[^A-Za-z0-9_-]", "_", os.path.basename(os.path.realpath(ctx.cwd))) or "dev"
    fix = (f'Run it in tmux so the logs stay readable: tmux new-session -d -s {name} "{cmd.strip()}" '
           f"then tmux capture-pane -t {name} -p -S -100. Or run it with run_in_background.")
    if ctx.profile == "strict":
        return {"block": "Blocked: a dev server started in the foreground ties up the shell and loses its logs. " + fix}
    return {"context": "Dev server outside tmux. " + fix}
