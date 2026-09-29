#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Deterministic Neva harness audit. Python 3 standard library only. Read-only.

Two target modes, detected from --root (default the current directory):
  repo      the Neva marketplace repo itself (.claude-plugin/marketplace.json plus plugins/neva-core):
            plugin manifests, hook wiring, script references, skill descriptions, model pins, tests.
  consumer  any other project: is Neva installed, enabled and firing on this machine, are its rules
            installed, is the MCP load inside budget, are instincts fresh, plus project hygiene.

Scoring and report shape follow the upstream audit: fixed categories, points per check, each
category normalized to 0-10, overall = earned points / applicable points, top 3 actions by points.
The same inputs give the same report; pass --now to pin the clock for the time-based checks.

Usage:
  python3 harness_audit.py [scope] [--format text|json] [--root <path>] [--home <dir>]
                           [--mcp-tools <n>] [--now <ISO date>]
  scope: repo (default) | hooks | skills | commands | agents

Inputs read (never written): ~/.claude.json, ~/.claude/settings.json, ~/.claude/plugins/,
~/.claude/rules/neva/, the Neva data dir (NEVA_DATA_DIR, else $XDG_DATA_HOME/neva, else
~/.local/share/neva) including hooks.log, and the vault (NEVA_VAULT or VAULT_PATH in
~/.config/neva/identity.env) for instincts.
"""
import datetime
import json
import os
import re
import sys

CATEGORIES = [
    "Tool Coverage",
    "Context Efficiency",
    "Quality Gates",
    "Memory Persistence",
    "Eval Coverage",
    "Security Guardrails",
    "Cost Efficiency",
    "GitHub Integration",
    "Vercel Integration",
    "Netlify Integration",
    "Cloudflare Integration",
    "Fly Integration",
]
RUBRIC_VERSION = "2026-09-29.neva"
SCOPES = ("repo", "hooks", "skills", "commands", "agents")

MCP_SERVER_LIMIT = 10          # enabled servers per project: fewer than this
MCP_TOOL_LIMIT = 80            # MCP tools loaded at once: fewer than this
SKILL_DESCRIPTION_MAX = 300    # characters, the listing budget
ACTIVITY_WINDOW_DAYS = 7       # hooks count as firing if they wrote something this recently
PENDING_INSTINCT_TTL_DAYS = 30
LEARNED_INSTINCT_STALE_DAYS = 90
MODEL_PINS = ("opus", "sonnet", "haiku")
SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             ".nuxt", "target", ".orchestration", "_upstream"}


class AuditError(Exception):
    pass


# ---------------------------------------------------------------- providers

def _exists(root, rel):
    return os.path.exists(os.path.join(root, rel))


PROVIDERS = {
    "Vercel": {
        "detect": lambda r: _exists(r, "vercel.json") or _exists(r, ".vercel/project.json") or _exists(r, ".vercel"),
        "key": re.compile(r"vercel", re.I), "build": re.compile(r"vercel", re.I),
        "workflow": re.compile(r"(vercel-action|vercel\s+(deploy|--prod))", re.I),
    },
    "Netlify": {
        "detect": lambda r: _exists(r, "netlify.toml") or _exists(r, ".netlify"),
        "key": re.compile(r"netlify", re.I), "build": re.compile(r"netlify", re.I),
        "workflow": re.compile(r"(netlify/actions|netlify\s+deploy)", re.I),
    },
    "Cloudflare": {
        "detect": lambda r: _exists(r, "wrangler.toml") or _exists(r, "wrangler.jsonc") or _exists(r, "wrangler.json"),
        "key": re.compile(r"\b(cloudflare|wrangler)\b", re.I), "build": re.compile(r"(wrangler|cloudflare)", re.I),
        "workflow": re.compile(r"(cloudflare/wrangler-action|wrangler\s+(deploy|publish))", re.I),
    },
    "Fly": {
        "detect": lambda r: _exists(r, "fly.toml"),
        "key": re.compile(r"fly[_-]?(api|io)", re.I), "build": re.compile(r"fly\s+(deploy|launch)", re.I),
        "workflow": re.compile(r"(superfly/flyctl-actions|flyctl\s+deploy|fly\s+deploy)", re.I),
    },
}


# ---------------------------------------------------------------- small io

def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def read_json(path):
    t = read_text(path)
    if not t.strip():
        return None
    try:
        return json.loads(t)
    except ValueError:
        return None


def walk_files(base, max_files=20000):
    """Yield file paths under base, skipping dependency and VCS folders."""
    if not os.path.isdir(base):
        return
    n = 0
    for d, dirs, names in os.walk(base):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for name in sorted(names):
            n += 1
            if n > max_files:
                return
            yield os.path.join(d, name)


def count_files(root, rel, suffix):
    return sum(1 for p in walk_files(os.path.join(root, rel)) if suffix is None or p.endswith(suffix))


def has_file_with(root, rel, suffixes):
    return any(p.endswith(tuple(suffixes)) for p in walk_files(os.path.join(root, rel)))


def mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def newest_mtime(paths):
    best = None
    for base in paths:
        if os.path.isfile(base):
            m = mtime(base)
            best = m if best is None or (m and m > best) else best
            continue
        for p in walk_files(base, max_files=5000):
            m = mtime(p)
            if m and (best is None or m > best):
                best = m
    return best


def iso_ts(ts):
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel_list(items, limit=5):
    items = list(items)
    head = ", ".join(items[:limit])
    return head + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


# ---------------------------------------------------------------- frontmatter

def frontmatter(text):
    """Minimal YAML frontmatter reader: top-level scalars, quoted strings, block scalars."""
    if not text.startswith("---"):
        return {}
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    out, i = {}, 1
    while i < end:
        line = lines[i]
        m = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        cont = []
        j = i + 1
        while j < end and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
            cont.append(lines[j])
            j += 1
        if value in (">", ">-", ">+", "|", "|-", "|+"):
            body = [c.strip() for c in cont]
            joiner = " " if value.startswith(">") else "\n"
            out[key] = joiner.join(b for b in body if b).strip()
        elif value[:1] in ("'", '"'):
            q = value[0]
            full = " ".join([value] + [c.strip() for c in cont if c.strip()])
            inner = full[1:]
            end_q = inner.rfind(q)
            inner = inner[:end_q] if end_q >= 0 else inner
            out[key] = inner.replace('\\"', '"') if q == '"' else inner.replace("''", "'")
        elif value == "" and cont:
            nested = any(re.match(r"^\s+[A-Za-z0-9_-]+:", c) or c.strip().startswith("- ") for c in cont)
            out[key] = None if nested else " ".join(c.strip() for c in cont if c.strip())
        else:
            extra = [c.strip() for c in cont if c.strip()]
            out[key] = " ".join([value] + extra) if extra and not any(":" in e for e in extra) else value
        i = j
    return out


# ---------------------------------------------------------------- environment

class Env:
    def __init__(self, root, home, now, mcp_tools, environ):
        self.root = root
        self.home = home
        self.now = now
        self.mcp_tools = mcp_tools
        self.environ = environ

    def get(self, key, default=""):
        return self.environ.get(key, default)

    @property
    def claude_dir(self):
        return os.path.join(self.home, ".claude")

    def data_dir(self):
        d = self.get("NEVA_DATA_DIR")
        if d:
            return os.path.expanduser(d)
        base = self.get("XDG_DATA_HOME") or os.path.join(self.home, ".local", "share")
        return os.path.join(base, "neva")

    def identity(self):
        path = os.path.expanduser(self.get("NEVA_CONFIG") or os.path.join(self.home, ".config", "neva", "identity.env"))
        out = {}
        for line in read_text(path).splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        return out

    def vault(self):
        v = self.get("NEVA_VAULT") or self.identity().get("VAULT_PATH", "")
        return os.path.expanduser(v) if v else ""


def settings_layers(env):
    """User, project, local. Later layers win."""
    return [read_json(os.path.join(env.claude_dir, "settings.json")) or {},
            read_json(os.path.join(env.root, ".claude", "settings.json")) or {},
            read_json(os.path.join(env.root, ".claude", "settings.local.json")) or {}]


def enabled_plugins(env):
    state = {}
    for layer in settings_layers(env):
        ep = layer.get("enabledPlugins")
        if isinstance(ep, dict):
            for k, v in ep.items():
                state[str(k)] = bool(v)
    return state


def plugin_name(key):
    return str(key).split("@", 1)[0]


def installed_plugins(env):
    """name -> {key, root} for every installed plugin with a manifest on disk."""
    found = {}
    manifests = [os.path.join(env.root, ".claude", "plugins", "installed_plugins.json"),
                 os.path.join(env.claude_dir, "plugins", "installed_plugins.json")]
    for mp in manifests:
        data = read_json(mp)
        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, dict):
            continue
        for key, entries in plugins.items():
            for entry in entries if isinstance(entries, list) else []:
                ip = entry.get("installPath") if isinstance(entry, dict) else None
                if not isinstance(ip, str) or not ip.strip():
                    continue
                root = ip if os.path.isabs(ip) else os.path.abspath(os.path.join(os.path.dirname(mp), ip))
                if os.path.exists(os.path.join(root, ".claude-plugin", "plugin.json")) or os.path.exists(
                        os.path.join(root, "plugin.json")):
                    found.setdefault(plugin_name(key), {"key": key, "root": root, "source": "installed_plugins.json"})
                    break
    cache = os.path.join(env.claude_dir, "plugins", "cache")
    if os.path.isdir(cache):
        for market in sorted(os.listdir(cache)):
            mdir = os.path.join(cache, market)
            if not os.path.isdir(mdir):
                continue
            for name in sorted(os.listdir(mdir)):
                if name in found or not name.startswith("neva-"):
                    continue
                pdir = os.path.join(mdir, name)
                versions = sorted((v for v in os.listdir(pdir) if os.path.isdir(os.path.join(pdir, v))),
                                  key=_version_key, reverse=True) if os.path.isdir(pdir) else []
                for v in versions:
                    root = os.path.join(pdir, v)
                    if os.path.exists(os.path.join(root, ".claude-plugin", "plugin.json")):
                        found[name] = {"key": f"{name}@{market}", "root": root, "source": "plugin cache"}
                        break
    pr = env.get("CLAUDE_PLUGIN_ROOT")
    if pr and "neva-core" not in found:
        manifest = read_json(os.path.join(pr, ".claude-plugin", "plugin.json")) or {}
        if manifest.get("name") == "neva-core":
            found["neva-core"] = {"key": "neva-core", "root": pr, "source": "CLAUDE_PLUGIN_ROOT"}
    return found


def _version_key(v):
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v)]


def neva_plugin_roots(env, mode):
    if mode == "repo":
        base = os.path.join(env.root, "plugins")
        return {n: os.path.join(base, n) for n in sorted(os.listdir(base))
                if n.startswith("neva-") and os.path.isdir(os.path.join(base, n))} if os.path.isdir(base) else {}
    return {n: v["root"] for n, v in sorted(installed_plugins(env).items()) if n.startswith("neva-")}


# ---------------------------------------------------------------- neva surfaces

def skill_description_findings(plugin_roots):
    over, missing, total = [], [], 0
    for pname, proot in plugin_roots.items():
        sdir = os.path.join(proot, "skills")
        if not os.path.isdir(sdir):
            continue
        for sname in sorted(os.listdir(sdir)):
            sk = os.path.join(sdir, sname, "SKILL.md")
            if not os.path.isfile(sk):
                continue
            total += 1
            desc = frontmatter(read_text(sk)).get("description")
            if not desc:
                missing.append(f"{pname}/{sname}")
            elif len(desc) > SKILL_DESCRIPTION_MAX:
                over.append(f"{pname}/{sname} ({len(desc)})")
    return total, over, missing


def agent_pin_findings(plugin_roots):
    unpinned, total = [], 0
    for pname, proot in plugin_roots.items():
        adir = os.path.join(proot, "agents")
        if not os.path.isdir(adir):
            continue
        for name in sorted(os.listdir(adir)):
            if not name.endswith(".md"):
                continue
            total += 1
            model = str(frontmatter(read_text(os.path.join(adir, name))).get("model") or "").strip().lower()
            if model not in MODEL_PINS and not model.startswith("claude-"):
                unpinned.append(f"{pname}/{name[:-3]} ({model or 'none'})")
    return total, unpinned


def hook_wiring_findings(core_root):
    """Registered: every event the module registry uses has a dispatch.py entry in hooks.json.
    Resolves: every module file exists and defines its function."""
    problems = []
    if not core_root:
        return ["neva-core not found"], set()
    hooks = read_json(os.path.join(core_root, "hooks", "hooks.json"))
    meta = read_json(os.path.join(core_root, "hooks", "hooks.meta.json"))
    if not isinstance(hooks, dict) or not isinstance(hooks.get("hooks"), dict):
        return ["hooks/hooks.json missing or not JSON"], set()
    if not isinstance(meta, dict) or not isinstance(meta.get("modules"), list):
        return ["hooks/hooks.meta.json missing or not JSON"], set()
    registered = set()
    for event, blocks in hooks["hooks"].items():
        for block in blocks if isinstance(blocks, list) else []:
            for h in (block.get("hooks") if isinstance(block, dict) else None) or []:
                cmd = str(h.get("command") or "") if isinstance(h, dict) else ""
                if "dispatch.py" in cmd:
                    parts = cmd.split("dispatch.py", 1)[1].replace('"', " ").split()
                    registered.add(event)
                    if parts[1:2]:
                        registered.add(f"{event}:{parts[1]}")
    needed = set()
    for m in meta["modules"]:
        for ev in m.get("events") or []:
            needed.add(ev)
            if ev not in registered:
                problems.append(f"{m.get('id')}: event {ev} has no dispatch.py entry")
        mod_path = os.path.join(core_root, "hooks", "neva_hooks", f"{m.get('module')}.py")
        fn = m.get("function") or "run"
        src = read_text(mod_path)
        if not src:
            problems.append(f"{m.get('id')}: neva_hooks/{m.get('module')}.py missing")
        elif not re.search(r"^def " + re.escape(fn) + r"\(", src, re.M):
            problems.append(f"{m.get('id')}: {fn}() not defined in neva_hooks/{m.get('module')}.py")
    return problems, registered


def meta_module_ids(core_root):
    meta = read_json(os.path.join(core_root, "hooks", "hooks.meta.json")) if core_root else None
    return {m.get("id") for m in (meta or {}).get("modules", []) if isinstance(m, dict)}


def plugin_root_refs(plugin_roots):
    missing, total = [], 0
    rx = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
    for pname, proot in plugin_roots.items():
        for sub in ("commands", "agents", "skills"):
            for p in walk_files(os.path.join(proot, sub)):
                if not p.endswith(".md"):
                    continue
                for m in rx.finditer(read_text(p)):
                    ref = m.group(1).rstrip(".,:;)")
                    if "<" in ref or "*" in ref:
                        continue
                    total += 1
                    if not os.path.exists(os.path.join(proot, ref)):
                        missing.append(f"{pname}/{os.path.relpath(p, proot)} -> {ref}")
    return total, sorted(set(missing))


# ---------------------------------------------------------------- mcp

def enabled_mcp_servers(env, plugins):
    claude_json = read_json(os.path.join(env.home, ".claude.json")) or {}
    projects = claude_json.get("projects") if isinstance(claude_json.get("projects"), dict) else {}
    proj = projects.get(env.root) or projects.get(os.path.realpath(env.root)) or {}
    disabled = set(proj.get("disabledMcpServers") or []) | set(proj.get("disabledMcpjsonServers") or [])
    neva_off = {x.strip() for x in env.get("NEVA_DISABLED_MCPS").split(",") if x.strip()}
    servers = []

    def add(names, origin, skip=()):
        for n in sorted(names):
            if n in disabled or n in skip:
                continue
            servers.append(f"{n} ({origin})")

    add((claude_json.get("mcpServers") or {}).keys(), "user")
    add((proj.get("mcpServers") or {}).keys(), "local")
    add(((read_json(os.path.join(env.root, ".mcp.json")) or {}).get("mcpServers") or {}).keys(), "project")
    enabled = enabled_plugins(env)
    for name, info in sorted(plugins.items()):
        if not enabled.get(info["key"]) and not any(plugin_name(k) == name and v for k, v in enabled.items()):
            continue
        cfg = read_json(os.path.join(info["root"], ".mcp.json")) or {}
        names = (cfg.get("mcpServers") or cfg or {}).keys() if isinstance(cfg, dict) else []
        manifest = read_json(os.path.join(info["root"], ".claude-plugin", "plugin.json")) or {}
        if isinstance(manifest.get("mcpServers"), dict):
            names = list(names) + list(manifest["mcpServers"].keys())
        add(names, f"plugin {name}", skip=neva_off if name.startswith("neva-") else ())
    return servers


def all_installed(env):
    """Every installed plugin (not just Neva), for MCP counting."""
    found = {}
    for mp in (os.path.join(env.claude_dir, "plugins", "installed_plugins.json"),):
        data = read_json(mp)
        plugins = data.get("plugins") if isinstance(data, dict) else None
        for key, entries in (plugins or {}).items():
            for entry in entries if isinstance(entries, list) else []:
                ip = entry.get("installPath") if isinstance(entry, dict) else None
                if isinstance(ip, str) and ip and os.path.isdir(ip):
                    found.setdefault(plugin_name(key), {"key": key, "root": ip})
    for name, info in installed_plugins(env).items():
        found.setdefault(name, info)
    return found


# ---------------------------------------------------------------- activity

def hooks_activity(env):
    d = env.data_dir()
    ts = newest_mtime([os.path.join(d, "sessions"), os.path.join(d, "observations"), os.path.join(d, "state"),
                       os.path.join(d, "costs.jsonl")])
    return ts


def hooks_log_errors(env):
    """Error lines in hooks.log (and its rotated .1) dated inside the activity window."""
    cutoff = env.now - datetime.timedelta(days=ACTIVITY_WINDOW_DAYS)
    errors = []
    base = os.path.join(env.data_dir(), "hooks.log")
    for p in (base + ".1", base):
        for line in read_text(p).splitlines():
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$", line)
            if not m:
                continue
            try:
                when = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if when >= cutoff.replace(tzinfo=None) and m.group(2).startswith("[error]"):
                errors.append(f"{m.group(1)} {m.group(2)[:120]}")
    return os.path.exists(base), errors


def instinct_findings(env):
    vault = env.vault()
    if not vault or not os.path.isdir(vault):
        return None, []
    root = os.path.join(vault, "06 Memory", "instincts")
    stale = []
    today = env.now.date()
    for p in walk_files(root, max_files=10000):
        if not p.endswith(".md"):
            continue
        meta = frontmatter(read_text(p))
        rel = os.path.relpath(p, root)
        pending = rel.split(os.sep)[0] == "pending"
        stamp = str(meta.get("updated") or meta.get("created") or "")[:10]
        try:
            age = (today - datetime.date.fromisoformat(stamp)).days
        except ValueError:
            m = mtime(p)
            age = (today - datetime.datetime.fromtimestamp(m, tz=datetime.timezone.utc).date()).days if m else 0
        limit = PENDING_INSTINCT_TTL_DAYS if pending else LEARNED_INSTINCT_STALE_DAYS
        if age > limit:
            stale.append(f"{rel} ({age}d)")
    return root, stale


# ---------------------------------------------------------------- check builders

def check(cid, category, points, scopes, path, description, passed, fix, detail=None):
    return {"id": cid, "category": category, "points": points, "scopes": scopes, "path": path,
            "description": description, "pass": bool(passed), "fix": fix, "detail": detail}


def github_checks(root):
    return [
        check("github-workflows", "GitHub Integration", 3, ["repo"], ".github/workflows/",
              "GitHub Actions workflows are checked in",
              has_file_with(root, ".github/workflows", [".yml", ".yaml"]),
              "Add at least one workflow under .github/workflows/ so CI runs on every PR."),
        check("github-pr-template", "GitHub Integration", 2, ["repo"], ".github/PULL_REQUEST_TEMPLATE.md",
              "A pull request template is configured",
              _exists(root, ".github/PULL_REQUEST_TEMPLATE.md") or _exists(root, ".github/pull_request_template.md"),
              "Add .github/PULL_REQUEST_TEMPLATE.md so PR descriptions follow a consistent shape."),
        check("github-issue-templates", "GitHub Integration", 2, ["repo"], ".github/ISSUE_TEMPLATE/",
              "Issue templates are configured",
              has_file_with(root, ".github/ISSUE_TEMPLATE", [".md", ".yml", ".yaml"]),
              "Add at least one issue template under .github/ISSUE_TEMPLATE/."),
        check("github-codeowners", "GitHub Integration", 1, ["repo"], ".github/CODEOWNERS",
              "A CODEOWNERS file routes reviews",
              _exists(root, "CODEOWNERS") or _exists(root, ".github/CODEOWNERS") or _exists(root, "docs/CODEOWNERS"),
              "Add a CODEOWNERS file so PRs auto-request the right reviewers."),
        check("github-dep-updates", "GitHub Integration", 2, ["repo"], ".github/dependabot.yml",
              "Automated dependency updates are configured",
              any(_exists(root, p) for p in (".github/dependabot.yml", ".github/dependabot.yaml", "renovate.json",
                                             ".github/renovate.json", ".renovaterc")),
              "Add a Dependabot or Renovate config so dependency updates land automatically."),
    ]


def workflows_text(root):
    return "\n".join(read_text(p) for p in walk_files(os.path.join(root, ".github", "workflows"))
                     if p.endswith((".yml", ".yaml")))


def provider_checks(root, package_json):
    providers = [n for n, spec in PROVIDERS.items() if spec["detect"](root)]
    if not providers:
        return []
    scripts = "\n".join(str(v) for v in ((package_json or {}).get("scripts") or {}).values())
    env_example = read_text(os.path.join(root, ".env.example")) + "\n" + read_text(os.path.join(root, ".env.sample"))
    wf = workflows_text(root)
    out = []
    for p in providers:
        spec, cat, low = PROVIDERS[p], f"{p} Integration", p.lower()
        out += [
            check(f"{low}-config", cat, 3, ["repo"], f"{p} config", f"{p} deployment config is checked in", True,
                  f"Commit {p} configuration so deploys are reproducible from source."),
            check(f"{low}-build-script", cat, 2, ["repo"], "package.json scripts", f"package.json scripts reference {p}",
                  bool(spec["build"].search(scripts)), f"Add a build or deploy script in package.json that runs {p}."),
            check(f"{low}-env-doc", cat, 2, ["repo"], ".env.example", f"{p} env keys are documented in .env.example",
                  bool(spec["key"].search(env_example)), f"Document {p} environment variables in .env.example."),
            check(f"{low}-workflow-uses", cat, 3, ["repo"], ".github/workflows/",
                  f"A GitHub workflow uses the {p} action or CLI", bool(spec["workflow"].search(wf)),
                  f"Reference the {p} action or CLI from a workflow under .github/workflows/."),
        ]
    return out


def count_test_files(root):
    n = 0
    for p in walk_files(root):
        b = os.path.basename(p)
        if (b.endswith((".test.js", ".test.ts", ".spec.js", ".spec.ts", "_test.go", "_test.py", "Test.php"))
                or (b.startswith("test_") and b.endswith(".py"))):
            n += 1
    return n


def count_test_cases(root):
    n = 0
    for p in walk_files(root):
        b = os.path.basename(p)
        if b.startswith("test_") and b.endswith(".py"):
            n += len(re.findall(r"^\s*def test_", read_text(p), re.M))
        elif b.endswith((".test.js", ".spec.js", ".test.ts", ".spec.ts")):
            n += len(re.findall(r"\b(?:it|test)\(", read_text(p)))
    return n


def repo_checks(env):
    root = env.root
    plugins = neva_plugin_roots(env, "repo")
    core = plugins.get("neva-core")
    market = read_json(os.path.join(root, ".claude-plugin", "marketplace.json")) or {}
    listed = {str(p.get("name")): str(p.get("source") or "") for p in market.get("plugins") or [] if isinstance(p, dict)}
    bad_market = sorted([f"{n} (no manifest at {s})" for n, s in listed.items()
                         if not os.path.exists(os.path.join(root, s, ".claude-plugin", "plugin.json"))]
                        + [f"{n} (not in marketplace.json)" for n in plugins if n not in listed])
    wiring, registered = hook_wiring_findings(core)
    ids = meta_module_ids(core)
    skills_total, over, missing_desc = skill_description_findings(plugins)
    agents_total, unpinned = agent_pin_findings(plugins)
    refs_total, missing_refs = plugin_root_refs(plugins)
    shipped_mcp = []
    for n, pr in plugins.items():
        cfg = read_json(os.path.join(pr, ".mcp.json")) or {}
        shipped_mcp += [f"{s} ({n})" for s in (cfg.get("mcpServers") or {})]
    tests_py = [p for p in walk_files(os.path.join(core or root, "hooks", "tests")) if os.path.basename(p).startswith("test_")]
    script_tests = [p for p in walk_files(os.path.join(core or root, "scripts", "tests")) if os.path.basename(p).startswith("test_")]
    cases = count_test_cases(os.path.join(root, "plugins")) + count_test_cases(os.path.join(root, "build"))
    c = "plugins/neva-core"
    return [
        check("marketplace-plugins", "Tool Coverage", 3, ["repo"], ".claude-plugin/marketplace.json",
              "Every plugin folder is listed in the marketplace and every listed plugin has a manifest",
              bool(listed) and not bad_market,
              "Sync .claude-plugin/marketplace.json with plugins/*/.claude-plugin/plugin.json.",
              rel_list(bad_market) if bad_market else f"{len(listed)} plugins"),
        check("hooks-config", "Tool Coverage", 2, ["repo", "hooks"], f"{c}/hooks/hooks.json",
              "hooks.json routes the core events through dispatch.py",
              {"SessionStart", "PreToolUse", "PostToolUse", "Stop"} <= registered,
              f"Register SessionStart, PreToolUse, PostToolUse and Stop to dispatch.py in {c}/hooks/hooks.json.",
              ", ".join(sorted(e for e in registered if ":" not in e)) or "nothing registered"),
        check("hooks-modules-resolve", "Tool Coverage", 2, ["repo", "hooks"], f"{c}/hooks/hooks.meta.json",
              "Every hook module in the registry has a registered event, a file and its function",
              not wiring, f"Fix the module entries in {c}/hooks/hooks.meta.json or add the missing functions.",
              rel_list(wiring) if wiring else f"{len(ids)} modules"),
        check("tool-agent-count", "Tool Coverage", 1, ["repo", "agents"], "plugins/*/agents/",
              "At least 10 agent definitions exist", agents_total >= 10,
              "Add or restore agent definitions under plugins/*/agents/.", f"{agents_total} agents"),
        check("tool-skill-count", "Tool Coverage", 1, ["repo", "skills"], "plugins/*/skills/",
              "At least 20 skill definitions exist", skills_total >= 20,
              "Add skill folders with SKILL.md under plugins/*/skills/.", f"{skills_total} skills"),
        check("plugin-root-refs", "Tool Coverage", 1, ["repo", "commands", "agents", "skills"], "plugins/*/{commands,agents,skills}/",
              "Every ${CLAUDE_PLUGIN_ROOT}/ path a command, agent or skill calls exists in its plugin",
              not missing_refs, "Port or ship the referenced files, or fix the paths.",
              rel_list(missing_refs) if missing_refs else f"{refs_total} references resolve"),
        check("skill-description-length", "Context Efficiency", 3, ["repo", "skills"], "plugins/*/skills/*/SKILL.md",
              f"Every skill has a description of {SKILL_DESCRIPTION_MAX} characters or fewer",
              skills_total > 0 and not over and not missing_desc,
              f"Shorten descriptions to {SKILL_DESCRIPTION_MAX} characters: when to use it, nothing else.",
              rel_list([f"{x} (no description)" for x in missing_desc] + over)
              if (over or missing_desc) else f"{skills_total} skills within budget"),
        check("context-strategic-compact", "Context Efficiency", 2, ["repo", "skills"], f"{c}/skills/strategic-compact/SKILL.md",
              "Strategic compaction guidance is present", _exists(root, f"{c}/skills/strategic-compact/SKILL.md"),
              f"Add {c}/skills/strategic-compact/SKILL.md."),
        check("context-suggest-compact-hook", "Context Efficiency", 2, ["repo", "hooks"], f"{c}/hooks/hooks.meta.json",
              "The suggest_compact hook module is registered", "suggest_compact" in ids,
              "Register the suggest_compact module in hooks.meta.json."),
        check("mcp-default-budget", "Context Efficiency", 3, ["repo"], "plugins/*/.mcp.json",
              f"Plugins ship fewer than {MCP_SERVER_LIMIT} default MCP servers in total",
              len(shipped_mcp) < MCP_SERVER_LIMIT,
              "Move stateless servers to CLI skills; keep the default set well under 10 (docs/harness/06-mcp-budget.md).",
              f"{len(shipped_mcp)} shipped" + (f": {rel_list(shipped_mcp)}" if shipped_mcp else "")),
        check("quality-hook-tests", "Quality Gates", 3, ["repo", "hooks"], f"{c}/hooks/tests/",
              "Hook runtime tests exist", bool(tests_py), f"Add unittest files under {c}/hooks/tests/."),
        check("quality-script-tests", "Quality Gates", 2, ["repo"], f"{c}/scripts/tests/",
              "Plugin script tests exist", bool(script_tests), f"Add unittest files under {c}/scripts/tests/."),
        check("quality-verify-script", "Quality Gates", 3, ["repo"], "build/verify.sh",
              "The end-to-end verify harness exists", _exists(root, "build/verify.sh"),
              "Add build/verify.sh that installs into a sandbox and runs every check."),
        check("quality-doctor", "Quality Gates", 2, ["repo"], "bin/doctor",
              "An install doctor exists", _exists(root, "bin/doctor"), "Add bin/doctor for install-state checks."),
        check("memory-session-hooks", "Memory Persistence", 4, ["repo", "hooks"], f"{c}/hooks/hooks.meta.json",
              "Session start and session summary modules are registered",
              {"session_start", "session_summary"} <= ids,
              "Register session_start (SessionStart) and session_summary (Stop) in hooks.meta.json."),
        check("memory-instincts-cli", "Memory Persistence", 2, ["repo", "hooks"], f"{c}/hooks/instincts.py",
              "The instinct CLI exists", _exists(root, f"{c}/hooks/instincts.py"), f"Add {c}/hooks/instincts.py."),
        check("memory-learning-skill", "Memory Persistence", 2, ["repo", "skills"], f"{c}/skills/continuous-learning-v2/SKILL.md",
              "Continuous learning skill exists", _exists(root, f"{c}/skills/continuous-learning-v2/SKILL.md"),
              f"Add {c}/skills/continuous-learning-v2/SKILL.md."),
        check("memory-vault-template", "Memory Persistence", 2, ["repo"], "vault/",
              "A vault template ships with the repo", os.path.isdir(os.path.join(root, "vault")),
              "Ship a vault/ template so memory has a home on first run."),
        check("eval-skill", "Eval Coverage", 4, ["repo", "skills"], f"{c}/skills/eval-harness/SKILL.md",
              "Eval harness skill exists", _exists(root, f"{c}/skills/eval-harness/SKILL.md"),
              f"Add {c}/skills/eval-harness/SKILL.md."),
        check("eval-commands", "Eval Coverage", 4, ["repo", "commands", "skills"], f"{c}/commands/checkpoint.md",
              "Checkpoint command plus eval-harness and verification-loop skills exist",
              all(_exists(root, f"{c}/{p}") for p in ("commands/checkpoint.md", "skills/eval-harness/SKILL.md",
                                                     "skills/verification-loop/SKILL.md")),
              "Add the checkpoint command plus eval-harness and verification-loop skills."),
        check("eval-tests-presence", "Eval Coverage", 2, ["repo"], "plugins/**/tests/",
              "At least 10 automated test cases exist", cases >= 10,
              "Increase automated test coverage across hooks and scripts.", f"{cases} test cases"),
        check("security-review-skill", "Security Guardrails", 3, ["repo", "skills"], f"{c}/skills/security-review/SKILL.md",
              "Security review skill exists", _exists(root, f"{c}/skills/security-review/SKILL.md"),
              f"Add {c}/skills/security-review/SKILL.md."),
        check("security-agent", "Security Guardrails", 3, ["repo", "agents"], f"{c}/agents/security-reviewer.md",
              "Security reviewer agent exists", _exists(root, f"{c}/agents/security-reviewer.md"),
              f"Add {c}/agents/security-reviewer.md."),
        check("security-pretool-hook", "Security Guardrails", 2, ["repo", "hooks"], f"{c}/hooks/hooks.json",
              "PreToolUse guardrails are registered", "PreToolUse" in registered,
              "Register PreToolUse in hooks.json (no_verify, config_protection, vault_gate)."),
        check("security-scan-command", "Security Guardrails", 2, ["repo", "commands"], f"{c}/commands/security-scan.md",
              "Security scan command exists", _exists(root, f"{c}/commands/security-scan.md"),
              f"Add {c}/commands/security-scan.md."),
        check("security-leak-scan", "Security Guardrails", 2, ["repo"], "build/leak-scan.py",
              "A leak scanner guards the public repo", _exists(root, "build/leak-scan.py"),
              "Add build/leak-scan.py and run it before every push."),
        check("cost-model-pins", "Cost Efficiency", 4, ["repo", "agents"], "plugins/*/agents/*.md",
              "Every agent pins a model (opus, sonnet or haiku)", agents_total > 0 and not unpinned,
              "Set model: opus for judgment, sonnet for mechanical work, haiku for pure lookup.",
              rel_list(unpinned) if unpinned else f"{agents_total} agents pinned"),
        check("cost-tracker-hook", "Cost Efficiency", 2, ["repo", "hooks"], f"{c}/hooks/hooks.meta.json",
              "The cost_tracker module is registered", "cost_tracker" in ids,
              "Register cost_tracker (Stop) in hooks.meta.json."),
        check("cost-model-route-command", "Cost Efficiency", 2, ["repo", "commands"], f"{c}/commands/model-route.md",
              "Model route command exists", _exists(root, f"{c}/commands/model-route.md"),
              f"Add {c}/commands/model-route.md."),
        check("cost-skill", "Cost Efficiency", 1, ["repo", "skills"], f"{c}/skills/cost-aware-llm-pipeline/SKILL.md",
              "Cost-aware LLM skill exists", _exists(root, f"{c}/skills/cost-aware-llm-pipeline/SKILL.md"),
              f"Add {c}/skills/cost-aware-llm-pipeline/SKILL.md."),
        check("cost-token-doc", "Cost Efficiency", 1, ["repo"], "docs/harness/02-token-economy.md",
              "Token economy documentation exists", _exists(root, "docs/harness/02-token-economy.md"),
              "Add docs/harness/02-token-economy.md."),
    ] + github_checks(root)


def has_tests(root, package_json):
    if isinstance(((package_json or {}).get("scripts") or {}).get("test"), str):
        return True
    for marker in ("pytest.ini", "phpunit.xml", "phpunit.xml.dist", "tox.ini"):
        if _exists(root, marker):
            return True
    if "[tool.pytest" in read_text(os.path.join(root, "pyproject.toml")):
        return True
    return count_test_files(root) > 0


def consumer_checks(env):
    root = env.root
    package_json = read_json(os.path.join(root, "package.json"))
    gitignore = read_text(os.path.join(root, ".gitignore"))
    project_hooks = read_text(os.path.join(root, ".claude", "settings.json"))
    installed = installed_plugins(env)
    core = installed.get("neva-core")
    core_root = core["root"] if core else None
    enabled = enabled_plugins(env)
    core_enabled = any(plugin_name(k) == "neva-core" and v for k, v in enabled.items()) or (
        bool(core) and core["source"] == "CLAUDE_PLUGIN_ROOT")
    hooks_off = any(layer.get("disableAllHooks") is True for layer in settings_layers(env))
    wiring, registered = hook_wiring_findings(core_root) if core_root else (["neva-core not installed"], set())
    plugins = neva_plugin_roots(env, "consumer")
    skills_total, over, missing_desc = skill_description_findings(plugins)
    agents_total, unpinned = agent_pin_findings(plugins)
    servers = enabled_mcp_servers(env, all_installed(env))
    last_activity = hooks_activity(env)
    cutoff = (env.now - datetime.timedelta(days=ACTIVITY_WINDOW_DAYS)).timestamp()
    firing = last_activity is not None and last_activity >= cutoff
    log_exists, log_errors = hooks_log_errors(env)
    vault = env.vault()
    inst_root, stale = instinct_findings(env)
    rules_dir = os.path.join(env.claude_dir, "rules", "neva", "common")
    shipped_rules = sorted(n for n in os.listdir(os.path.join(core_root, "rules"))
                           if n.endswith(".md") and n != "README.md") if core_root and os.path.isdir(
        os.path.join(core_root, "rules")) else []
    have_rules = set(os.listdir(rules_dir)) if os.path.isdir(rules_dir) else set()
    missing_rules = [r for r in shipped_rules if r not in have_rules]
    rules_ok = (not missing_rules) if shipped_rules else bool(have_rules)
    costs = mtime(os.path.join(env.data_dir(), "costs.jsonl"))
    tests_n = count_test_files(root)
    tools = env.mcp_tools

    return [
        check("neva-core-installed", "Tool Coverage", 4, ["repo"], "~/.claude/plugins/installed_plugins.json",
              "The neva-core plugin is installed for this user or project", bool(core),
              "Install Neva: /plugin marketplace add <neva repo>, then /plugin install neva-core@neva.",
              f"{core['key']} via {core['source']}" if core else "not found"),
        check("neva-core-enabled", "Tool Coverage", 2, ["repo", "hooks"], "~/.claude/settings.json",
              "neva-core is enabled in enabledPlugins", core_enabled,
              'Set "neva-core@neva": true under enabledPlugins in ~/.claude/settings.json, or run /plugin enable.'),
        check("consumer-project-overrides", "Tool Coverage", 3, list(SCOPES), ".claude/",
              "Project-specific harness overrides exist under .claude/",
              count_files(root, ".claude/agents", ".md") > 0 or count_files(root, ".claude/skills", "SKILL.md") > 0
              or count_files(root, ".claude/commands", ".md") > 0 or _exists(root, ".claude/settings.json")
              or _exists(root, ".claude/hooks.json"),
              "Add project-local .claude hooks, commands, skills, or settings that tailor Neva to this repo."),
        check("hooks-registered", "Tool Coverage", 2, ["repo", "hooks"], "neva-core/hooks/hooks.json",
              "Neva hooks are registered, every module resolves, and hooks are not disabled",
              bool(core_root) and not wiring and not hooks_off,
              "Reinstall neva-core so hooks.json and hooks.meta.json match, and remove disableAllHooks from settings.",
              "disableAllHooks is true" if hooks_off else (rel_list(wiring) if wiring else f"{len(meta_module_ids(core_root))} modules")),
        check("consumer-instructions", "Context Efficiency", 3, ["repo"], "AGENTS.md",
              "The project has explicit agent or instruction context",
              _exists(root, "AGENTS.md") or _exists(root, "CLAUDE.md") or _exists(root, ".claude/CLAUDE.md"),
              "Add AGENTS.md or CLAUDE.md so the harness has project-specific instructions."),
        check("consumer-project-config", "Context Efficiency", 2, ["repo", "hooks"], ".mcp.json",
              "The project declares local MCP or Claude settings",
              _exists(root, ".mcp.json") or _exists(root, ".claude/settings.json") or _exists(root, ".claude/settings.local.json"),
              "Add .mcp.json or .claude/settings.json so project-local tool configuration is explicit."),
        check("mcp-server-budget", "Context Efficiency", 3, ["repo"], "~/.claude.json mcpServers",
              f"Fewer than {MCP_SERVER_LIMIT} MCP servers are enabled for this project",
              len(servers) < MCP_SERVER_LIMIT,
              "Disable servers this project does not use: disabledMcpServers in the project entry of ~/.claude.json, "
              "or NEVA_DISABLED_MCPS for Neva's own.",
              f"{len(servers)} enabled" + (f": {rel_list(servers, 12)}" if servers else "")),
        check("mcp-tool-budget", "Context Efficiency", 2, ["repo"], "MCP tools in the session",
              f"Fewer than {MCP_TOOL_LIMIT} MCP tools are loaded",
              tools is not None and tools < MCP_TOOL_LIMIT,
              "Re-run with --mcp-tools <count of mcp__ tools in your tool list>; if it is 80 or more, disable servers."
              if tools is None else "Disable MCP servers until fewer than 80 mcp__ tools load.",
              "not measured (pass --mcp-tools)" if tools is None else f"{tools} tools"),
        check("skill-description-length", "Context Efficiency", 2, ["repo", "skills"], "neva-*/skills/*/SKILL.md",
              f"Every installed Neva skill has a description of {SKILL_DESCRIPTION_MAX} characters or fewer",
              skills_total > 0 and not over and not missing_desc,
              "Update the Neva plugins; report skills over budget upstream.",
              rel_list([f"{x} (no description)" for x in missing_desc] + over)
              if (over or missing_desc) else f"{skills_total} skills"),
        check("consumer-test-suite", "Quality Gates", 4, ["repo"], "tests/",
              "The project has an automated test entrypoint", has_tests(root, package_json),
              "Add a test script or checked-in tests so harness recommendations can be verified automatically."),
        check("consumer-ci-workflow", "Quality Gates", 3, ["repo"], ".github/workflows/",
              "The project has CI workflows checked in", has_file_with(root, ".github/workflows", [".yml", ".yaml"]),
              "Add at least one CI workflow so harness and test checks run outside local development."),
        check("consumer-memory-notes", "Memory Persistence", 2, ["repo"], ".claude/memory.md",
              "Project memory or durable notes are checked in",
              _exists(root, ".claude/memory.md") or count_files(root, "docs/adr", ".md") > 0,
              "Add durable project memory such as .claude/memory.md or ADRs under docs/adr/."),
        check("hooks-firing", "Memory Persistence", 3, ["repo", "hooks"], "~/.local/share/neva/",
              f"Neva hooks wrote session, observation or state files in the last {ACTIVITY_WINDOW_DAYS} days", firing,
              "Start a session with neva-core enabled, then check ~/.local/share/neva/hooks.log for the first error.",
              f"last activity {iso_ts(last_activity)}" if last_activity else "no activity found"),
        check("hooks-log-clean", "Memory Persistence", 2, ["repo", "hooks"], "~/.local/share/neva/hooks.log",
              f"hooks.log has no module errors in the last {ACTIVITY_WINDOW_DAYS} days", not log_errors,
              "Read the [error] lines in hooks.log, fix the failing module, or disable it with NEVA_DISABLED_HOOKS.",
              (f"{len(log_errors)} errors, last: {log_errors[-1]}" if log_errors
               else ("no errors" if log_exists else "no hooks.log yet"))),
        check("vault-configured", "Memory Persistence", 2, ["repo"], "~/.config/neva/identity.env",
              "The Neva vault is configured and present", bool(vault) and os.path.isdir(vault),
              "Set NEVA_VAULT, or VAULT_PATH in ~/.config/neva/identity.env, to the vault folder.",
              "configured" if vault and os.path.isdir(vault) else ("path missing" if vault else "not set")),
        check("instincts-fresh", "Memory Persistence", 2, ["repo"], "<vault>/06 Memory/instincts/",
              f"No pending instinct is past its {PENDING_INSTINCT_TTL_DAYS} day TTL and none learned is older than "
              f"{LEARNED_INSTINCT_STALE_DAYS} days", inst_root is not None and not stale,
              "Run /prune for pending instincts and /instinct-status to review stale learned ones.",
              ("vault not configured" if inst_root is None else (rel_list(stale) if stale else "fresh"))),
        check("consumer-eval-coverage", "Eval Coverage", 2, ["repo"], "evals/",
              "The project has evals or multiple automated tests",
              count_files(root, "evals", None) > 0 or tests_n >= 3,
              "Add eval fixtures or at least a few focused automated tests for critical flows.", f"{tests_n} test files"),
        check("consumer-security-policy", "Security Guardrails", 2, ["repo"], "SECURITY.md",
              "The project exposes a security policy or automated dependency scanning",
              _exists(root, "SECURITY.md") or _exists(root, ".github/dependabot.yml") or _exists(root, ".github/codeql.yml"),
              "Add SECURITY.md or dependency/code scanning configuration to document the project security posture."),
        check("consumer-secret-hygiene", "Security Guardrails", 2, ["repo"], ".gitignore",
              "The project ignores common secret env files", ".env" in gitignore,
              "Ignore .env-style files in .gitignore so secrets do not land in the repo."),
        check("consumer-hook-guardrails", "Security Guardrails", 2, ["repo", "hooks"], ".claude/settings.json",
              "PreToolUse guardrails are active (project hooks or enabled neva-core)",
              "PreToolUse" in project_hooks or _exists(root, ".claude/hooks.json")
              or (core_enabled and "PreToolUse" in registered and not hooks_off),
              "Enable neva-core, or add project-local PreToolUse hooks."),
        check("rules-installed", "Security Guardrails", 3, ["repo"], "~/.claude/rules/neva/common/",
              "Neva core rules are installed where Claude Code reads them", rules_ok,
              "Copy plugins/neva-core/rules/*.md to ~/.claude/rules/neva/common/ (see rules/README.md).",
              (f"missing {rel_list(missing_rules)}" if missing_rules else
               (f"{len(have_rules)} rule files" if have_rules else "folder missing or empty"))),
        check("cost-model-pins", "Cost Efficiency", 3, ["repo", "agents"], "neva-*/agents/*.md",
              "Every installed Neva agent pins a model", agents_total > 0 and not unpinned,
              "Update the Neva plugins; unpinned agents inherit the session model and cost more.",
              rel_list(unpinned) if unpinned else f"{agents_total} agents"),
        check("cost-tracking-active", "Cost Efficiency", 2, ["repo", "hooks"], "~/.local/share/neva/costs.jsonl",
              f"The cost tracker wrote in the last {ACTIVITY_WINDOW_DAYS} days", costs is not None and costs >= cutoff,
              "Use the standard or strict NEVA_HOOK_PROFILE so cost_tracker runs at Stop.",
              f"last write {iso_ts(costs)}" if costs else "no costs.jsonl"),
    ] + github_checks(root) + provider_checks(root, package_json)


# ---------------------------------------------------------------- report

def detect_target_mode(root):
    market = read_json(os.path.join(root, ".claude-plugin", "marketplace.json")) or {}
    if market.get("name") == "neva" and _exists(root, "plugins/neva-core/.claude-plugin/plugin.json"):
        return "repo"
    return "consumer"


def js_round(x):
    return int(x + 0.5)


def summarize_categories(checks):
    scores = {}
    for cat in CATEGORIES:
        inside = [c for c in checks if c["category"] == cat]
        mx = sum(c["points"] for c in inside)
        earned = sum(c["points"] for c in inside if c["pass"])
        scores[cat] = {"score": 0 if mx == 0 else js_round(earned / mx * 10), "earned": earned, "max": mx}
    return scores


def build_report(scope="repo", root=None, home=None, now=None, mcp_tools=None, target_mode=None, environ=None):
    if scope not in SCOPES:
        raise AuditError(f"scope: '{scope}' is not valid. Use one of: {', '.join(SCOPES)}")
    root = os.path.abspath(root or os.getcwd())
    if not os.path.isdir(root):
        raise AuditError(f"--root: {root} is not a directory")
    environ = dict(os.environ if environ is None else environ)
    home = os.path.abspath(os.path.expanduser(home or environ.get("HOME") or os.path.expanduser("~")))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    env = Env(root, home, now, mcp_tools, environ)
    mode = target_mode or detect_target_mode(root)
    checks = [c for c in (repo_checks(env) if mode == "repo" else consumer_checks(env)) if scope in c["scopes"]]
    cats = summarize_categories(checks)
    applicable = [c for c in CATEGORIES if cats[c]["max"] > 0]
    failed = sorted([c for c in checks if not c["pass"]], key=lambda c: -c["points"])
    return {
        "scope": scope,
        "root_dir": root,
        "target_mode": mode,
        "deterministic": True,
        "rubric_version": RUBRIC_VERSION,
        "generated_for": now.strftime("%Y-%m-%d"),
        "overall_score": sum(c["points"] for c in checks if c["pass"]),
        "max_score": sum(c["points"] for c in checks),
        "categories": cats,
        "applicable_categories": applicable,
        "category_count": len(applicable),
        "checks": [{k: c[k] for k in ("id", "category", "points", "path", "description", "pass", "detail")}
                   for c in checks],
        "top_actions": [{"action": c["fix"], "path": c["path"], "category": c["category"], "points": c["points"]}
                        for c in failed[:3]],
    }


def format_text(r):
    lines = [f"Harness Audit ({r['scope']}, {r['target_mode']}): {r['overall_score']}/{r['max_score']}",
             f"Root: {r['root_dir']}", ""]
    for cat in CATEGORIES:
        d = r["categories"].get(cat)
        if d and d["max"]:
            lines.append(f"- {cat}: {d['score']}/10 ({d['earned']}/{d['max']} pts)")
    failed = [c for c in r["checks"] if not c["pass"]]
    lines += ["", f"Checks: {len(r['checks'])} total, {len(failed)} failing"]
    if failed:
        lines += ["", "Top 3 Actions:"]
        for i, a in enumerate(r["top_actions"], 1):
            lines.append(f"{i}) [{a['category']}] {a['action']} ({a['path']})")
        lines += ["", "Failing checks:"]
        for c in failed:
            lines.append(f"- {c['id']} ({c['points']} pts) {c['path']}" + (f": {c['detail']}" if c.get("detail") else ""))
    return "\n".join(lines)


USAGE = """Usage: python3 harness_audit.py [scope] [--scope <repo|hooks|skills|commands|agents>] [--format <text|json>]
                           [--root <path>] [--home <dir>] [--mcp-tools <n>] [--now <YYYY-MM-DD or ISO>]

Deterministic Neva harness audit based on explicit file and config checks. Read-only.
Audits the current working directory by default and auto-detects Neva repo mode vs consumer mode."""


def parse_now(v):
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.datetime.fromisoformat(s) if "T" in s else datetime.datetime.combine(
            datetime.date.fromisoformat(s), datetime.time(12, 0))
    except ValueError:
        raise AuditError(f"--now: '{v}' is not a date. Use YYYY-MM-DD or an ISO timestamp.")
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def parse_args(argv):
    o = {"scope": "repo", "format": "text", "help": False, "root": os.environ.get("AUDIT_ROOT") or os.getcwd(),
         "home": None, "mcp_tools": None, "now": None}
    i = 0

    def value(flag):
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            raise AuditError(f"{flag} requires a value")
        return argv[i + 1]

    while i < len(argv):
        a = argv[i]
        key, eq, inline = a.partition("=") if a.startswith("--") else (a, "", "")
        if a in ("--help", "-h"):
            o["help"] = True
        elif key in ("--format", "--scope", "--root", "--home", "--mcp-tools", "--now"):
            v = inline if eq else value(key)
            if not eq:
                i += 1
            if key == "--format":
                o["format"] = v.lower()
            elif key == "--scope":
                o["scope"] = v.lower()
            elif key == "--root":
                o["root"] = v
            elif key == "--home":
                o["home"] = v
            elif key == "--mcp-tools":
                if not re.fullmatch(r"\d+", v):
                    raise AuditError(f"--mcp-tools: '{v}' is not a whole number. Count the mcp__ tools in your tool list.")
                o["mcp_tools"] = int(v)
            else:
                o["now"] = parse_now(v)
        elif a.startswith("-"):
            raise AuditError(f"Unknown argument: {a}. Run with --help for the list.")
        else:
            o["scope"] = a.lower()
        i += 1
    if o["format"] not in ("text", "json"):
        raise AuditError(f"--format: '{o['format']}' is not valid. Use text or json.")
    if o["scope"] not in SCOPES:
        raise AuditError(f"scope: '{o['scope']}' is not valid. Use one of: {', '.join(SCOPES)}")
    return o


def main(argv=None):
    try:
        o = parse_args(sys.argv[1:] if argv is None else list(argv))
        if o["help"]:
            print(USAGE)
            return 0
        report = build_report(o["scope"], root=o["root"], home=o["home"], now=o["now"], mcp_tools=o["mcp_tools"])
        print(json.dumps(report, indent=2, ensure_ascii=False) if o["format"] == "json" else format_text(report))
        return 0
    except AuditError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
