# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Stop: runs once per response.

Module ids:
  session_summary   refresh this session's state file between the NEVA:SUMMARY markers
  cost_tracker      append a cumulative cost snapshot to <NEVA_METRICS_DIR>/costs.jsonl
                    (default ~/.local/share/neva/metrics) when usage changed
  format_typecheck  format the files this response edited, with the project's own tools only
                    (biome, prettier, pint, ruff); strict profile also runs tsc and feeds its
                    errors back once
  journal_nudge     once per session: block the stop when 5+ tool calls ran and nothing was
                    written to the journal
  notify            optional macOS notification (NEVA_NOTIFY=1)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import common as c
from .session_end import journal_written


# ---------------------------------------------------------------- session_summary

def session_summary(ctx):
    t = ctx.transcript
    if not t["ok"] or not t["prompts"]:
        return None
    c.update_session_file(ctx, c.summary_markdown(t))
    return None


# ---------------------------------------------------------------- cost_tracker

RATES = {  # USD per million tokens: input, output, cache write, cache read (estimates)
    "haiku": (1.00, 5.00, 1.25, 0.10),
    "sonnet": (3.00, 15.00, 3.75, 0.30),
    "opus": (5.00, 25.00, 6.25, 0.50),
    "opus_legacy": (15.00, 75.00, 18.75, 1.50),
    "fable": (10.00, 50.00, 12.50, 1.00),
}


def rates_for(model):
    m = (model or "").lower()
    if "fable" in m or "mythos" in m:
        return RATES["fable"]
    if "haiku" in m:
        return RATES["haiku"]
    if re.search(r"3-opus|opus-4-0(?!\d)|opus-4-1(?!\d)|opus-4[-@]\d{8}", m):
        return RATES["opus_legacy"]
    if "opus" in m:
        return RATES["opus"]
    return RATES["sonnet"]


def cost_tracker(ctx):
    t = ctx.transcript
    if not t["usage"]:
        return None
    tot = {"input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0}
    for u in t["usage"].values():
        tot["input_tokens"] += int(u.get("input_tokens") or 0)
        tot["output_tokens"] += int(u.get("output_tokens") or 0)
        tot["cache_write_tokens"] += int(u.get("cache_creation_input_tokens") or 0)
        tot["cache_read_tokens"] += int(u.get("cache_read_input_tokens") or 0)
    if not any(tot.values()):
        return None
    last_p = ctx.state_file("cost") + ".json"
    if c.read_json(last_p) == tot:
        return None
    r = rates_for(t["model"])
    cost = (tot["input_tokens"] * r[0] + tot["output_tokens"] * r[1] + tot["cache_write_tokens"] * r[2]
            + tot["cache_read_tokens"] * r[3]) / 1e6
    row = {"timestamp": c.now().isoformat(timespec="seconds"), "session_id": ctx.session_id or "default",
           "transcript_path": ctx.transcript_path, "project": ctx.project["name"],
           "model": t["model"] or "unknown", **tot, "estimated_cost_usd": round(cost, 6)}
    with open(c.costs_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    c.write_json(last_p, tot)
    return None


# ---------------------------------------------------------------- format_typecheck

ROOT_MARKERS = ("package.json", "biome.json", "biome.jsonc", "composer.json", "pyproject.toml", "ruff.toml",
                ".ruff.toml", ".git")
PRETTIER_CONFIGS = (".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.mjs",
                    ".prettierrc.yml", ".prettierrc.yaml", ".prettierrc.toml", "prettier.config.js",
                    "prettier.config.cjs", "prettier.config.mjs")
PRETTIER_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json", ".css", ".scss", ".md", ".html",
                ".vue", ".yaml", ".yml")
BIOME_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json", ".jsonc", ".css")


def project_root(path):
    d = os.path.dirname(path)
    stop_at = c.home()
    while d and d != os.path.dirname(d) and d != stop_at:
        if any(os.path.exists(os.path.join(d, m)) for m in ROOT_MARKERS):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(path)


def _exe(root, *rel):
    p = os.path.join(root, *rel)
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else None


def _run(argv, cwd, timeout):
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as e:
        return 127, str(e)


def formatters_for(root, files):
    """[(label, argv)] for the tools this project actually has installed. Never downloads."""
    jobs = []
    js = [f for f in files if f.endswith(PRETTIER_EXT)]
    biome = _exe(root, "node_modules", ".bin", "biome")
    has_biome_cfg = any(os.path.exists(os.path.join(root, n)) for n in ("biome.json", "biome.jsonc"))
    if js and biome and has_biome_cfg:
        fs = [f for f in js if f.endswith(BIOME_EXT)]
        if fs:
            jobs.append(("biome", [biome, "check", "--write", *fs]))
    elif js:
        prettier = _exe(root, "node_modules", ".bin", "prettier")
        pkg = c.read_json(os.path.join(root, "package.json"), {}) or {}
        has_cfg = "prettier" in pkg or any(os.path.exists(os.path.join(root, n)) for n in PRETTIER_CONFIGS)
        if prettier and has_cfg:
            jobs.append(("prettier", [prettier, "--write", *js]))
    php = [f for f in files if f.endswith(".php")]
    pint = _exe(root, "vendor", "bin", "pint")
    if php and pint:
        jobs.append(("pint", [pint, *php]))
    py = [f for f in files if f.endswith(".py")]
    if py:
        ruff = _exe(root, ".venv", "bin", "ruff") or shutil.which("ruff")
        pyproject = c.read_text(os.path.join(root, "pyproject.toml"))
        has_cfg = "[tool.ruff" in pyproject or any(os.path.exists(os.path.join(root, n)) for n in ("ruff.toml", ".ruff.toml"))
        if ruff and has_cfg:
            jobs.append(("ruff", [ruff, "format", *py]))
    return jobs


def tsconfig_dir(path):
    d = os.path.dirname(path)
    for _ in range(20):
        if os.path.exists(os.path.join(d, "tsconfig.json")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def format_typecheck(ctx):
    acc = ctx.state_file("edited") + ".txt"
    if not os.path.exists(acc):
        return None
    work = acc + f".{os.getpid()}"
    try:
        os.replace(acc, work)
        raw = c.read_text(work)
    finally:
        try:
            os.remove(work)
        except OSError:
            pass
    plugin_dirs = [os.path.join(c.home(), ".claude", "plugins")]
    files = []
    for f in dict.fromkeys(ln.strip() for ln in raw.splitlines() if ln.strip()):
        if os.path.isfile(f) and not any(f.startswith(p + os.sep) for p in plugin_dirs):
            files.append(f)
    if not files:
        return None
    budget = c.env_int("NEVA_FORMAT_BUDGET_S", 240, 5, 600)
    deadline = time.time() + budget
    by_root = {}
    for f in files:
        by_root.setdefault(project_root(f), []).append(f)
    notes = []
    for root, fs in by_root.items():
        for label, argv in formatters_for(root, fs):
            left = deadline - time.time()
            if left <= 1:
                notes.append(f"{label}: skipped, out of time budget ({budget}s)")
                continue
            code, out = _run(argv, root, min(60, left))
            if code != 0:
                notes.append(f"{label} exited {code} in {root}: {c.one_line(out, 300)}")
    result = {}
    if notes:
        result["system"] = "Format after edits:\n" + "\n".join(f"- {n}" for n in notes)
    if ctx.profile != "strict" or ctx.data.get("stop_hook_active"):
        return result or None
    errors = []
    by_ts = {}
    for f in files:
        if f.endswith((".ts", ".tsx")):
            d = tsconfig_dir(f)
            if d:
                by_ts.setdefault(d, []).append(f)
    for d, fs in by_ts.items():
        tsc = _exe(d, "node_modules", ".bin", "tsc") or _exe(project_root(fs[0]), "node_modules", ".bin", "tsc")
        left = deadline - time.time()
        if not tsc or left <= 1:
            continue
        code, out = _run([tsc, "--noEmit", "--pretty", "false", "-p", d], d, min(120, left))
        if code in (0, 124, 127):
            continue
        for f in fs:
            rel = os.path.relpath(f, d)
            hits = [ln for ln in out.splitlines() if rel in ln or f in ln][:10]
            if hits:
                errors.append(f"{rel}:\n" + "\n".join(f"  {h}" for h in hits))
    if errors:
        result["block"] = ("TypeScript errors in files edited this response. Fix them before finishing:\n"
                           + "\n".join(errors))
    return result or None


# ---------------------------------------------------------------- journal_nudge

def journal_nudge(ctx):
    if ctx.data.get("stop_hook_active") or not ctx.vault:
        return None
    if not ctx.transcript_path or not os.path.exists(ctx.transcript_path):
        return None
    marker = ctx.state_file("journal-asked")
    if os.path.exists(marker):
        return None
    t = ctx.transcript
    need = c.env_int("NEVA_JOURNAL_NUDGE_MIN_TOOLS", 5, 1)
    if len(t["tool_uses"]) < need or journal_written(t):
        return None
    with open(marker, "w") as fh:
        fh.write("1")
    return {"block": (f"Before finishing: append 2 to 4 lines to today's journal ({c.journal_path()}) under "
                      f"{c.log_heading()}: what moved, wins, blockers, tagged [{ctx.project['name']}]. If a "
                      "durable lesson was learned, say so in the answer. Then stop.")}


# ---------------------------------------------------------------- notify

def notify(ctx):
    if not c.env_flag("NEVA_NOTIFY") or sys.platform != "darwin" or not shutil.which("osascript"):
        return None
    t = ctx.transcript
    last = c.one_line(t["prompts"][-1], 80) if t["prompts"] else "Response ready"
    body = last.replace("\\", "").replace('"', "'")
    title = f"Claude Code: {ctx.project['name']}".replace('"', "'")
    try:
        subprocess.Popen(["osascript", "-e", f'display notification "{body}" with title "{title}"'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass
    return None
