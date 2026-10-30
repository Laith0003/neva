#!/usr/bin/env python3
"""check-plugin-refs: fail on any reference to a skill, command or agent that will not resolve.

neva-core is always on. neva-library is opt-in, so a session may run with it disabled. A core
file that sends the model to a library item by an invocable name sends it to nothing. And a
library file that points at `neva-core:<name>` after <name> moved to the library is broken in
every session. This checker reads the plugins listed in .claude-plugin/marketplace.json and
enforces three rules. Standard library only.

R1 namespaced  `<plugin>:<name>` (for every plugin in the marketplace, anywhere it is scanned)
               must name a skill, command or agent that plugin ships.
R2 opt-in      a file in any plugin other than neva-library must not use a library-only item
               (one no other plugin ships) by a bare name: `/<name>`, `subagent_type: <name>`,
               a backticked or bold `<name>`, a table cell, `pair with <name>`, prose
               `<name> skill|agent|subagent|command`, `Skill(<name>)`, or a path built as
               "skills", "<name>" in code. Name it
               `neva-library:<name>` and say the library is opt-in; R1 then proves it exists.
R3 paths       every `${CLAUDE_PLUGIN_ROOT}/<path>` or `$CLAUDE_PLUGIN_ROOT/<path>` must exist
               inside the plugin that holds the file. In neva-library it must also exist in
               neva-core, because Codex and the adapters read library files with the root set
               to plugins/neva-core. `neva_core.py path|run <path>` must exist in neva-core,
               `neva_core.py library <path>` in neva-library, and the two helper copies must
               be byte-identical.

Scanned: every text file under plugins/ (tests excluded: fixtures name things on purpose),
docs/, and the top-level Markdown files except CHANGELOG.md (history describes old layouts).

    python3 build/check-plugin-refs.py [--root DIR]
Exit 0 clean, 1 on any dangling reference, 2 on a broken repo layout.
"""
import argparse
import json
import re
import sys
from pathlib import Path

CORE = "neva-core"
LIBRARY = "neva-library"
TEXT = {".md", ".py", ".js", ".mjs", ".cjs", ".json", ".sh", ".toml", ".yaml", ".yml", ".txt"}
NAME = r"[a-z0-9][a-z0-9-]*"
ROOT_REF = re.compile(r"(?:\$(?:\{CLAUDE_PLUGIN_ROOT\}|CLAUDE_PLUGIN_ROOT(?![\w}]))"
                      r"|process\.env\.CLAUDE_PLUGIN_ROOT\s*\+\s*['\"])/([A-Za-z0-9_./-]+)")
HELPER = "scripts/neva_core.py"
HELPER_REF = re.compile(r"neva_core\.py\"?\s+(path|run|library)\s+([A-Za-z0-9_./-]+)")


def frontmatter_name(path):
    """The `name:` an agent or command declares, or None. Claude Code uses it over the stem."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    for line in text[4:end].split("\n"):
        if line.startswith("name:"):
            value = line[5:].strip().strip("'\"")
            return value or None
    return None


def components(plugin_root):
    """Every invocable name a plugin ships, mapped to its kind."""
    found = {}
    skills = plugin_root / "skills"
    if skills.is_dir():
        for d in sorted(skills.iterdir()):
            if (d / "SKILL.md").is_file():
                found[d.name] = "skill"
    for kind in ("commands", "agents"):
        folder = plugin_root / kind
        if folder.is_dir():
            for f in sorted(folder.glob("*.md")):
                found[f.stem] = kind[:-1]
                declared = frontmatter_name(f)
                if declared and declared != f.stem:
                    found[declared] = kind[:-1]
    return found


def load_plugins(root):
    market = root / ".claude-plugin" / "marketplace.json"
    try:
        listed = json.loads(market.read_text(encoding="utf-8"))["plugins"]
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"check-plugin-refs: cannot read {market}: {exc}. Fix the marketplace manifest.")
    plugins = {}
    for entry in listed:
        source = (root / entry["source"]).resolve()
        if not (source / ".claude-plugin" / "plugin.json").is_file():
            print(f"check-plugin-refs: {entry['name']} has no manifest at {entry['source']}", file=sys.stderr)
            sys.exit(2)
        plugins[entry["name"]] = (source, components(source))
    if CORE not in plugins:
        print("check-plugin-refs: neva-core is not in the marketplace", file=sys.stderr)
        sys.exit(2)
    return plugins


def scanned_files(root):
    tops = [p for p in sorted(root.glob("*.md")) if p.name != "CHANGELOG.md"]
    trees = [root / "plugins", root / "docs"]
    for top in tops:
        yield top
    for tree in trees:
        if not tree.is_dir():
            continue
        for path in sorted(tree.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT:
                continue
            parts = path.relative_to(root).parts
            if "tests" in parts or "node_modules" in parts or "__pycache__" in parts:
                continue
            yield path


def owner(path, plugins):
    for name, (proot, _) in plugins.items():
        if proot == path or proot in path.parents:
            return name, proot
    return None, None


def line_of(text, index):
    return text.count("\n", 0, index) + 1


def check(root):
    root = Path(root).resolve()
    plugins = load_plugins(root)
    core_root, _ = plugins[CORE]
    library_root = plugins[LIBRARY][0] if LIBRARY in plugins else None
    library_names = plugins[LIBRARY][1] if LIBRARY in plugins else {}
    elsewhere = {n for p, (_, names) in plugins.items() if p != LIBRARY for n in names}
    library_only = sorted(n for n in library_names if n not in elsewhere)
    namespaced = re.compile(r"(?<![\w-])(" + "|".join(re.escape(p) for p in plugins) + r"):(" + NAME + r")")
    bare = None
    if library_only:
        alt = "|".join(re.escape(n) for n in sorted(library_only, key=len, reverse=True))
        bare = re.compile(r"(?<![\w/.~:>})*$-])/(" + alt + r")(?![\w-])"
                          r"|subagent_type\W{1,4}(" + alt + r")(?![\w-])"
                          r"|`(" + alt + r")`"
                          r"|(?<![\w:/.`-])(" + alt + r")\s+(?:skill|agent|subagent|command)s?\b"
                          r"|\bSkill\(\s*[\"']?(" + alt + r")(?![\w-])"
                          r"|\*\*(" + alt + r")\*\*"
                          r"|\|[ \t]+(" + alt + r")[ \t]+(?=\|)"
                          r"|\b[Pp]air with\s+(" + alt + r")\b"
                          r"|[\"']skills[\"']\s*[,/]\s*[\"'](" + alt + r")[\"']")
    findings = []

    def report(path, text, index, rule, ref, fix):
        findings.append(f"{path.relative_to(root)}:{line_of(text, index)}: {rule}: {ref}: {fix}")

    for path in scanned_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        plugin, proot = owner(path, plugins)
        for m in namespaced.finditer(text):
            target, name = m.group(1), m.group(2)
            if name not in plugins[target][1]:
                where = [p for p, (_, names) in plugins.items() if name in names]
                fix = (f"it lives in {', '.join(where)}; write {where[0]}:{name}" if where
                       else f"{target} ships no skill, command or agent named {name}")
                report(path, text, m.start(), "R1 namespaced", m.group(0), fix)
        if plugin is not None and plugin != LIBRARY and bare is not None:
            for m in bare.finditer(text):
                name = next(g for g in m.groups() if g)
                report(path, text, m.start(), "R2 opt-in", m.group(0),
                       f"{name} is in the opt-in neva-library; write neva-library:{name} and say it is opt-in")
        if proot is not None:
            for m in ROOT_REF.finditer(text):
                ref = m.group(1).rstrip(".,:;)")
                if not ref:
                    continue
                if not (proot / ref).exists():
                    report(path, text, m.start(), "R3 paths", m.group(0),
                           f"{ref} does not exist in {plugin}; fix the path or run it through neva_core.py")
                elif plugin == LIBRARY and not (core_root / ref).exists():
                    report(path, text, m.start(), "R3 paths", m.group(0),
                           f"{ref} fails when CLAUDE_PLUGIN_ROOT names neva-core (Codex and the adapters); "
                           f"write \"$(python3 \"${{CLAUDE_PLUGIN_ROOT}}/{HELPER}\" library {ref})\"")
        for m in HELPER_REF.finditer(text):
            ref = m.group(2).rstrip(".,:;)")
            target, name = (library_root, LIBRARY) if m.group(1) == "library" else (core_root, CORE)
            if target is None or not (target / ref).exists():
                report(path, text, m.start(), "R3 paths", m.group(0), f"{ref} does not exist in {name}")
    if library_root is not None:
        copies = [core_root / HELPER, library_root / HELPER]
        if all(c.is_file() for c in copies) and copies[0].read_bytes() != copies[1].read_bytes():
            findings.append(f"{HELPER}: R3 paths: the neva-core and neva-library copies differ: "
                            "keep them byte-identical")
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                        help="repository root holding .claude-plugin/marketplace.json")
    args = parser.parse_args(argv)
    findings = check(args.root)
    for line in findings:
        print(line)
    if findings:
        print(f"check-plugin-refs: {len(findings)} dangling reference(s)")
        return 1
    print("check-plugin-refs: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
