# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""PreToolUse on Write, Edit and MultiEdit (tool filter in hooks.meta.json): vault write gate,
config protection, doc file warning, strategic compaction nudge.

Module ids: vault_gate, config_protection, doc_file_warning, suggest_compact.

suggest_compact is the one implementation of the strategic-compact skill's nudge:
  context signal  newest transcript usage (input + cache read + cache creation). Threshold
                  COMPACT_CONTEXT_THRESHOLD, default 160000 on a 200k window and 800000 on a 1M
                  window; repeats every COMPACT_CONTEXT_INTERVAL (60000) more tokens; 0 disables.
                  Window: NEVA_CONTEXT_WINDOW_TOKENS, else CLAUDE_CODE_AUTO_COMPACT_WINDOW, else a
                  [1m] marker or a 1M model family in the model id, else inferred (>200k seen).
  count fallback  only when the transcript has no usage yet: at COMPACT_THRESHOLD (50) edits,
                  then every 25.
  state           <state dir>/hooks/compact-<session>.json, pruned after COMPACT_STATE_TTL_DAYS.
"""
import difflib
import os
import re

from . import common as c

DEFAULT_WRITABLE = "08 Journal,00 Inbox,06 Memory,09 Reviews,inbox.md"


# ---------------------------------------------------------------- vault_gate

def vault_gate(ctx):
    vault = ctx.vault
    fp = ctx.file_path()
    if not vault or not fp:
        return None
    real = os.path.realpath(os.path.expanduser(fp))
    if not real.startswith(vault + os.sep):
        return None
    rel = os.path.relpath(real, vault)
    allowed = [a.strip().strip("/") for a in (c.env("NEVA_VAULT_WRITABLE") or DEFAULT_WRITABLE).split(",") if a.strip()]
    if any(rel == a or rel.startswith(a + os.sep) for a in allowed):
        return None
    return {"ask": (f"Vault write outside the session folders: {rel}. Sessions write freely only in: "
                    f"{', '.join(allowed)} (NEVA_VAULT_WRITABLE). Structure and canon notes change with the "
                    "owner's OK, so confirm this one.")}


# ---------------------------------------------------------------- config_protection

PROTECTED = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml",
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", "eslint.config.mts",
    "eslint.config.cts", ".prettierrc", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.json",
    ".prettierrc.yml", ".prettierrc.yaml", "prettier.config.js", "prettier.config.cjs", "prettier.config.mjs",
    "biome.json", "biome.jsonc", ".ruff.toml", "ruff.toml", ".shellcheckrc", ".stylelintrc",
    ".stylelintrc.json", ".stylelintrc.yml", ".markdownlint.json", ".markdownlint.yaml", ".markdownlintrc",
    "tsconfig.json", "jsconfig.json", "mypy.ini", ".mypy.ini", "pyrightconfig.json", ".flake8", ".pylintrc",
    "pylintrc", "pyproject.toml", "setup.cfg", "phpstan.neon", "phpstan.neon.dist", "pint.json",
    ".php-cs-fixer.php", ".php-cs-fixer.dist.php", ".golangci.yml", ".golangci.yaml", "rustfmt.toml",
    ".rustfmt.toml", "clippy.toml", ".rubocop.yml", ".swiftlint.yml",
}
STRICT_KEYS = (r"strict|noImplicitAny|strictNullChecks|strictFunctionTypes|noUnusedLocals|noUnusedParameters|"
               r"noImplicitReturns|noFallthroughCasesInSwitch|noUncheckedIndexedAccess|exactOptionalPropertyTypes|"
               r"checkJs|forceConsistentCasingInFileNames|disallow_untyped_defs|disallow_any_generics|"
               r"warn_unused_ignores|strict_optional|check_untyped_defs|declare_strict_types")
LOOSEN_PATTERNS = [
    (re.compile(r"[\"']?\b(" + STRICT_KEYS + r")\b[\"']?\s*[:=]\s*(false|False|0)\b"), "turns off a strictness flag"),
    (re.compile(r"[\"'][\w/@.-]+[\"']\s*:\s*\[?\s*([\"'](off|warn|warning|info)[\"']|0\b)"), "turns a rule off or down to a warning"),
    (re.compile(r"^\s*[\w/@.-]+\s*:\s*\[?\s*(off|warn|0)\s*\]?\s*$"), "turns a rule off or down to a warning"),
    (re.compile(r"(?i)\b(ignore|ignores|ignorePatterns|ignore_errors|ignore_missing_imports|exclude|excludes|"
                r"extend-ignore|per-file-ignores|skipLibCheck|disable|disabled|skip|allow_untyped)\b"),
     "adds an ignore, exclude, skip or disable entry"),
]
RULE_LINE = re.compile(r"(?i)(\b(" + STRICT_KEYS + r")\b|[\"'][\w/@.-]+[\"']\s*:\s*\[?\s*[\"']?(error|2)\b|"
                       r"\b(select|extend-select|rules)\b)")
LEVEL = re.compile(r"^\s*level\s*[:=]\s*(\d+)")
# Files that mix lint settings with unrelated config: only lint/type sections are judged.
MIXED = {"pyproject.toml", "setup.cfg"}
LINT_SECTION = re.compile(r"(?i)^(tool\.(ruff|mypy|pyright|black|isort|pylint|flake8|pydocstyle|basedpyright)"
                          r"(\.|$)|flake8$|mypy(-|$)|pylint|pycodestyle|pydocstyle|isort$)")


def _is_protected(name):
    low = name.lower()
    return name in PROTECTED or low in PROTECTED or re.match(r"^tsconfig\..+\.json$", low) is not None


def _sections(lines, start=""):
    cur, out = start, []
    for ln in lines:
        m = re.match(r"^\s*\[+([^\]]+)\]+\s*$", ln)
        if m:
            cur = m.group(1).strip()
        out.append(cur)
    return out


def _section_at(text, needle):
    i = text.find(needle) if needle else -1
    return _sections(text[:i].splitlines())[-1] if i > 0 and text[:i].splitlines() else ""


def _changes(ctx, fp):
    """(removed, added) lists of (line, section) this tool call would apply to fp."""
    ti = ctx.tool_input
    current = c.read_text(fp)
    pairs = []
    if ctx.tool_name == "Write":
        pairs.append((current, str(ti.get("content") or ""), ""))
    elif ctx.tool_name == "Edit":
        old = str(ti.get("old_string") or "")
        pairs.append((old, str(ti.get("new_string") or ""), _section_at(current, old)))
    elif ctx.tool_name == "MultiEdit":
        for e in ti.get("edits") or []:
            if isinstance(e, dict):
                old = str(e.get("old_string") or "")
                pairs.append((old, str(e.get("new_string") or ""), _section_at(current, old)))
    removed, added = [], []
    for old, new, base in pairs:
        a, b = old.splitlines(), new.splitlines()
        sa, sb = _sections(a, base), _sections(b, base)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag in ("replace", "delete"):
                removed += list(zip(a[i1:i2], sa[i1:i2]))
            if tag in ("replace", "insert"):
                added += list(zip(b[j1:j2], sb[j1:j2]))
    return removed, added


def loosening(removed, added, mixed=False):
    if mixed:
        removed = [(ln, s) for ln, s in removed if LINT_SECTION.match(s)]
        added = [(ln, s) for ln, s in added if LINT_SECTION.match(s)]
    reasons = []
    added_text = "\n".join(ln for ln, _ in added)
    for line, _ in added:
        for rx, why in LOOSEN_PATTERNS:
            if rx.search(line):
                reasons.append((why, line.strip()))
                break
    old_levels = [int(m.group(1)) for m in (LEVEL.match(ln) for ln, _ in removed) if m]
    new_levels = [int(m.group(1)) for m in (LEVEL.match(ln) for ln, _ in added) if m]
    if old_levels and new_levels and min(new_levels) < max(old_levels):
        reasons.append(("lowers the analysis level", f"level {max(old_levels)} to {min(new_levels)}"))
    for line, _ in removed:
        if not RULE_LINE.search(line):
            continue
        key = re.search(r"[\"']?([\w/@.-]+)[\"']?\s*[:=]", line)
        if key and key.group(1) in added_text:
            continue  # the setting is still there, only its value changed (judged above)
        reasons.append(("removes a rule or strictness setting", line.strip()))
    return reasons


def config_protection(ctx):
    fp = ctx.file_path()
    if not fp or ctx.tool_name not in ("Write", "Edit", "MultiEdit"):
        return None
    name = os.path.basename(fp)
    if not _is_protected(name) or not os.path.exists(fp):
        return None
    reasons = loosening(*_changes(ctx, fp), mixed=name.lower() in MIXED)
    if not reasons:
        return None
    shown = "\n".join(f"  - {why}: `{c.one_line(line, 100)}`" for why, line in reasons[:5])
    return {"block": (f"Blocked: this edit loosens {name}:\n{shown}\nFix the code so it satisfies the rule instead "
                      "of weakening the config. If the user explicitly asked for this config change, tell them it "
                      "was blocked and that NEVA_DISABLED_HOOKS=config_protection allows it for their session.")}


# ---------------------------------------------------------------- doc_file_warning

ADHOC = re.compile(r"^(NOTES|TODO|SCRATCH|TEMP|DRAFT|BRAINSTORM|SPIKE|DEBUG|WIP)\.(md|txt)$")
STRUCTURED = re.compile(r"(^|/)(docs|\.claude|\.github|commands|skills|benchmarks|templates|\.history|memory)/")


def doc_file_warning(ctx):
    fp = ctx.file_path().replace("\\", "/")
    if ctx.tool_name != "Write" or not fp:
        return None
    if ADHOC.match(os.path.basename(fp)) and not STRUCTURED.search(fp):
        return {"context": (f"Ad-hoc documentation file: {fp}. Put notes in a structured place (docs/, "
                            ".claude/, templates/) or in the answer itself, not a loose file at the repo root.")}
    return None


# ---------------------------------------------------------------- suggest_compact

STANDARD_WINDOW = 200_000
LARGE_WINDOW = 1_000_000
LARGE_MODELS = ("claude-opus-5", "claude-fable-5", "claude-mythos-5")


def context_window(tokens, model):
    w = c.env_int("NEVA_CONTEXT_WINDOW_TOKENS", 0, 1) or c.env_int("CLAUDE_CODE_AUTO_COMPACT_WINDOW", 0, 1)
    if w:
        return w
    m = (model or "").lower()
    if "[1m]" in m or any(re.search(re.escape(f) + r"(?![a-z0-9])(?!-[a-z])", m) for f in LARGE_MODELS):
        return LARGE_WINDOW
    return LARGE_WINDOW if tokens > STANDARD_WINDOW else STANDARD_WINDOW


def suggest_compact(ctx):
    st_p = ctx.state_file("compact") + ".json"
    st = c.read_json(st_p, {}) or {}
    st["count"] = int(st.get("count", 0)) + 1
    msg = None
    tokens, model = c.context_tokens(ctx.transcript_path) if ctx.transcript_path else (0, "")
    if tokens:
        window = context_window(tokens, model)
        default_thr = 800_000 if window >= LARGE_WINDOW else 160_000
        thr = c.env_int("COMPACT_CONTEXT_THRESHOLD", default_thr, 0)
        interval = c.env_int("COMPACT_CONTEXT_INTERVAL", 60_000, 1)
        if thr > 0 and tokens >= thr:
            bucket = (tokens - thr) // interval
            if bucket > int(st.get("bucket", -1)):
                st["bucket"] = bucket
                pct = round(tokens * 100 / window)
                msg = (f"[StrategicCompact] Context is about {round(tokens / 1000)}k tokens ({pct}% of a "
                       f"{window // 1000}k window). Consider /compact at the next logical boundary, with a focus "
                       "line for what comes next. Write the plan or state to a file first (/ck:save).")
    else:
        thr = c.env_int("COMPACT_THRESHOLD", 50, 1, 10000)
        n = st["count"]
        if n == thr or (n > thr and (n - thr) % 25 == 0):
            msg = (f"[StrategicCompact] {n} edits this session. A good checkpoint for /compact if the phase "
                   "is changing.")
    c.write_json(st_p, st)
    return {"context": msg} if msg else None
