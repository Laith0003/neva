"""Compile the files the owner lists into capped tiers for any model's system prompt.

Nothing is collected by default. The pack holds only what the include list in the omni config
names, because the worker sends it as the system prompt to every configured provider.
"""
import datetime, glob, json, os, re

TIERS = {"small": 8000, "medium": 32000, "large": 120000}
ORDER = ["include", "rules", "lessons", "taste", "memory"]
# Key shapes refused in any source file. Mirrors the token patterns in build/leak-scan.py
# (a test fails if that list gains one this lacks) plus the providers this pack is sent to.
# The scanner is not imported: build/ is not installed, so lib/ cannot depend on it.
SECRETS = [
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-style key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("groq key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("google api key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("telegram bot token", re.compile(r"\d{8,10}:AA[0-9A-Za-z_-]{30,}|\b\d{5,16}:A[A-Za-z0-9_-]{33,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.")),
    ("github token", re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("aws access key", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

CONFIG_ENV = "NEVA_OMNI_CONFIG"
DEFAULT_CONFIG = os.path.join("~", ".config", "neva", "omni.json")

# The ids in omni/worker/src/providers.js; a test fails if the two lists drift apart.
PROVIDERS = (("workers-ai", "Cloudflare Workers AI"), ("groq", "Groq"), ("gemini", "Google Gemini"))


def _read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    for label, shape in SECRETS:
        if shape.search(text):
            raise ValueError(f"secret-shaped text ({label}) in {path}: remove it, or drop the file "
                             "from include in the omni config, then compile again")
    return re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()


def compile_pack(sources, tiers):
    blocks = []
    for kind in ORDER:
        for path in sources.get(kind, []):
            blocks.append((kind, path, _read(path)))
    out = {}
    for name, cap in tiers.items():
        parts, used = [], 0
        for kind, path, text in blocks:
            label = os.path.basename(path) if kind == "include" else f"{kind}: {os.path.basename(path)}"
            piece = f"\n\n## {label}\n{text}"
            if used + len(piece) > cap:
                room = cap - used
                if room > 200:
                    parts.append(piece[:room].rsplit("\n", 1)[0])
                    used += len(parts[-1])
                break
            parts.append(piece); used += len(piece)
        text = "".join(parts).strip()
        out[name] = {"text": text, "chars": len(text)}
    return {"version": 1, "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tiers": out, "sources": [{"path": p, "bytes": os.path.getsize(p)} for _, p, _ in blocks]}


def config_path(explicit=None):
    chosen = explicit or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG
    return os.path.abspath(os.path.expandvars(os.path.expanduser(chosen)))


def load_config(path):
    """The omni config. A missing file is the default: an empty include list."""
    fix = f'write {path} as {{"include": ["path/or/glob.md"]}}'
    try:
        with open(path, encoding="utf-8") as stream:
            config = json.load(stream)
    except FileNotFoundError:
        return {"include": []}
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"omni config {path} is not JSON ({error}): {fix}") from None
    if not isinstance(config, dict):
        raise ValueError(f"omni config {path}: expected a JSON object; {fix}")
    include = config.get("include", [])
    if not isinstance(include, list) or not all(isinstance(entry, str) and entry.strip() for entry in include):
        raise ValueError(f"omni config {path}: field include must be a list of paths or globs; {fix}")
    return dict(config, include=include)


def _protected(path):
    """Why a globbed file needs an exact path, or None. Checks the link and its target."""
    for candidate in (os.path.abspath(path), os.path.realpath(path)):
        parts = [part.lower() for part in candidate.split(os.sep) if part]
        if parts and parts[-1] == "memory.md":
            return "MEMORY.md is sent only when listed by exact path"
        if any("confidential" in part for part in parts):
            return "a confidential file or folder is sent only when listed by exact path"
    return None


def select_sources(config, base):
    """Resolve the include list against base: (included paths, [(skipped path, reason)])."""
    included, skipped, seen = [], [], set()

    def add(path):
        key = os.path.realpath(path)
        if key not in seen:
            seen.add(key)
            included.append(path)

    for entry in config.get("include", []):
        expanded = os.path.expandvars(os.path.expanduser(entry))
        full = os.path.abspath(os.path.join(base, expanded))
        if glob.has_magic(expanded):
            matches = sorted(p for p in glob.glob(full, recursive=True) if os.path.isfile(p))
            if not matches:
                raise ValueError(f"include entry {entry} matched no files: fix the pattern or remove it")
            for path in matches:
                reason = _protected(path)
                if reason:
                    skipped.append((path, reason))
                else:
                    add(path)
        elif os.path.isdir(full):
            raise ValueError(f"include entry {entry} is a directory: list its files or a glob like {entry.rstrip('/')}/*.md")
        elif not os.path.isfile(full):
            raise ValueError(f"include entry {entry}: no such file at {full}; fix the path or remove it")
        else:
            add(full)
    return included, skipped


def describe_sources(pack):
    """One line per source file in a compiled pack. Refuses a pack that does not list them."""
    sources = pack.get("sources") if isinstance(pack, dict) else None
    valid = (isinstance(sources, list) and sources and
             all(isinstance(s, dict) and isinstance(s.get("path"), str) and isinstance(s.get("bytes"), int)
                 for s in sources))
    if not valid:
        raise ValueError("the brain pack's field sources is missing or does not list each file with its "
                         "size: recompile it with neva brainpack so you can see what it holds")
    return [f"  {s['path']} ({s['bytes']} bytes)" for s in sources]


def provider_line():
    names = ", ".join(f"{pid} ({label})" for pid, label in PROVIDERS)
    return f"the worker sends this pack as the system prompt to every provider configured on it: {names}"
