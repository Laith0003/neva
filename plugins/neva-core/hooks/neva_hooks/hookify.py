# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Hookify rule engine: user-written rules in `.claude/hookify.<name>.local.md`.

Rules are found in the nearest `.claude/` folder at or above the working directory (and in
CLAUDE_PROJECT_DIR/.claude when it is set). Each rule is markdown with frontmatter:

  name: block-rm-rf          required, kebab-case
  enabled: true              false skips the rule
  event: bash                bash | file | prompt | stop | all
  action: warn               warn (default) adds the message as context; block denies
  pattern: rm\\s+-rf          regex; or a `conditions:` list (all must match)

Events and fields:
  bash    PreToolUse on Bash                    command
  file    PreToolUse on Edit, Write, MultiEdit  file_path, new_text, old_text, content
  prompt  UserPromptSubmit                      user_prompt
  stop    Stop                                  transcript (last 20000 chars of the transcript)
A bare `pattern` matches command (bash), file_path or new_text (file), user_prompt (prompt) or
transcript (stop). Operators: regex_match, contains, equals, not_contains, starts_with,
ends_with.

A malformed rule is reported once per session as context and skipped; it never blocks. A stop
rule never blocks twice in a row (stop_hook_active), so a `.*` block rule cannot loop.
Module ids: hookify_pre_tool, hookify_prompt, hookify_stop.
"""
import glob
import os
import re

from . import common as c

EVENTS = ("bash", "file", "prompt", "stop", "all")
OPERATORS = ("regex_match", "contains", "equals", "not_contains", "starts_with", "ends_with")
FIELDS = {"bash": ("command",), "file": ("file_path", "new_text", "old_text", "content"),
          "prompt": ("user_prompt",), "stop": ("transcript",)}
DEFAULT_FIELDS = {"bash": ("command",), "file": ("file_path", "new_text"), "prompt": ("user_prompt",),
                  "stop": ("transcript",)}


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def parse_rule(text):
    """(rule dict, message). Frontmatter subset: top-level `key: value` and a `conditions:`
    list of `- field/operator/pattern` maps."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, ""
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None, ""
    rule, conds, cur, in_conds = {}, [], None, False
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[:1] in (" ", "\t")
        if not indented:
            in_conds = False
            key, _, val = raw.partition(":")
            key = key.strip()
            if key == "conditions" and not val.strip():
                in_conds = True
                continue
            rule[key] = _unquote(val)
            continue
        if not in_conds:
            continue
        item = raw.strip()
        if item.startswith("- "):
            cur = {}
            conds.append(cur)
            item = item[2:]
        if cur is not None and ":" in item:
            k, _, v = item.partition(":")
            cur[k.strip()] = _unquote(v)
    if conds:
        rule["conditions"] = conds
    return rule, "\n".join(lines[end + 1:]).strip()


def validate(rule):
    """Return an error that names the field and the fix, or ''."""
    if not rule.get("name"):
        return "`name` is missing. Fix: add `name: <kebab-case-id>` to the frontmatter."
    ev = rule.get("event", "")
    if ev not in EVENTS:
        return f"`event` is '{ev}'. Fix: use one of {', '.join(EVENTS)}."
    act = rule.get("action", "warn") or "warn"
    if act not in ("warn", "block"):
        return f"`action` is '{act}'. Fix: use warn or block."
    conds = rule.get("conditions") or []
    if not rule.get("pattern") and not conds:
        return "no `pattern` and no `conditions`. Fix: add `pattern: <regex>` (use `.*` to always match)."
    for n, cond in enumerate(conds, 1):
        if cond.get("operator", "regex_match") not in OPERATORS:
            return f"condition {n} `operator` is '{cond.get('operator')}'. Fix: use one of {', '.join(OPERATORS)}."
        if not cond.get("field"):
            return f"condition {n} has no `field`. Fix: add `field:` (for example command or file_path)."
    for pat in [rule.get("pattern")] + [x.get("pattern") for x in conds
                                        if x.get("operator", "regex_match") == "regex_match"]:
        if pat:
            try:
                re.compile(pat)
            except re.error as e:
                return f"`pattern` {pat!r} is not a valid regex ({e}). Fix: escape special characters."
    return ""


def rule_dirs(ctx):
    dirs = []
    proj = c.env("CLAUDE_PROJECT_DIR")
    if proj:
        dirs.append(os.path.join(proj, ".claude"))
    d = os.path.realpath(ctx.cwd)
    stop_at = os.path.realpath(c.home())
    while True:
        dirs.append(os.path.join(d, ".claude"))
        parent = os.path.dirname(d)
        if d == stop_at or parent == d:
            break
        d = parent
    seen, out = set(), []
    for x in dirs:
        r = os.path.realpath(x)
        if r not in seen and os.path.isdir(r):
            seen.add(r)
            out.append(r)
    return out


def load_rules(ctx):
    rules, problems = [], []
    for d in rule_dirs(ctx):
        for p in sorted(glob.glob(os.path.join(d, "hookify.*.local.md"))):
            rule, msg = parse_rule(c.read_text(p))
            if rule is None:
                problems.append((p, "no frontmatter block. Fix: start the file with --- and close it with ---."))
                continue
            if str(rule.get("enabled", "true")).strip().lower() in c.FALSE_VALUES:
                continue
            err = validate(rule)
            if err:
                problems.append((p, err))
                continue
            rule["_message"] = msg or f"hookify rule {rule['name']} matched."
            rule["_path"] = p
            rules.append(rule)
        if rules or problems:
            break  # nearest .claude folder with rules wins
    return rules, problems


def _check(op, value, pat):
    value = value or ""
    if op == "regex_match":
        return re.search(pat, value) is not None
    if op == "contains":
        return pat in value
    if op == "equals":
        return value == pat
    if op == "not_contains":
        return pat not in value
    if op == "starts_with":
        return value.startswith(pat)
    if op == "ends_with":
        return value.endswith(pat)
    return False


def matches(rule, kind, fields):
    if rule["event"] not in (kind, "all"):
        return False
    conds = rule.get("conditions") or []
    if conds:
        return all(_check(x.get("operator", "regex_match"), fields.get(x.get("field", "")), x.get("pattern", ""))
                   for x in conds)
    return any(_check("regex_match", fields.get(f), rule["pattern"]) for f in DEFAULT_FIELDS[kind])


def _file_fields(ctx):
    ti = ctx.tool_input
    fields = {"file_path": ctx.file_path()}
    if ctx.tool_name == "Write":
        fields["new_text"] = fields["content"] = str(ti.get("content") or "")
        fields["old_text"] = ""
    elif ctx.tool_name == "MultiEdit":
        edits = [e for e in ti.get("edits") or [] if isinstance(e, dict)]
        fields["new_text"] = "\n".join(str(e.get("new_string") or "") for e in edits)
        fields["old_text"] = "\n".join(str(e.get("old_string") or "") for e in edits)
        fields["content"] = fields["new_text"]
    else:
        fields["new_text"] = fields["content"] = str(ti.get("new_string") or "")
        fields["old_text"] = str(ti.get("old_string") or "")
    return fields


def _report_once(ctx, problems):
    if not problems:
        return ""
    marker = ctx.state_file("hookify-reported") + ".txt"
    seen = set(c.read_text(marker).splitlines())
    fresh = [(p, e) for p, e in problems if f"{p}|{e}" not in seen]
    if not fresh:
        return ""
    with open(marker, "a", encoding="utf-8") as fh:
        for p, e in fresh:
            fh.write(f"{p}|{e}\n")
    return "\n".join(f"hookify: skipped {os.path.basename(p)}: {e}" for p, e in fresh)


def _evaluate(ctx, kind, fields, may_block=True):
    rules, problems = load_rules(ctx)
    notes = [x for x in [_report_once(ctx, problems)] if x]
    blocks = []
    for r in rules:
        if not matches(r, kind, fields):
            continue
        line = f"[hookify:{r['name']}] {r['_message']}"
        if (r.get("action") or "warn") == "block" and may_block:
            blocks.append(line)
        else:
            notes.append(line)
    out = {}
    if blocks:
        out["block"] = "\n\n".join(blocks)
    if notes:
        out["context"] = "\n".join(notes)
    return out or None


def pre_tool(ctx):
    if ctx.tool_name == "Bash":
        return _evaluate(ctx, "bash", {"command": str(ctx.tool_input.get("command") or "")})
    if ctx.tool_name in ("Edit", "Write", "MultiEdit"):
        return _evaluate(ctx, "file", _file_fields(ctx))
    return None


def prompt(ctx):
    return _evaluate(ctx, "prompt", {"user_prompt": str(ctx.data.get("prompt") or "")})


def _transcript_tail(path, n=20000):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - n))
            return fh.read().decode("utf-8", "ignore")
    except OSError:
        return ""


def stop(ctx):
    fields = {"transcript": _transcript_tail(ctx.transcript_path) if ctx.transcript_path else ""}
    return _evaluate(ctx, "stop", fields, may_block=not ctx.data.get("stop_hook_active"))
