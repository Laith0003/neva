#!/usr/bin/env python3
"""Reach a file in neva-core or neva-library whichever plugin ${CLAUDE_PLUGIN_ROOT} names.

Claude Code sets ${CLAUDE_PLUGIN_ROOT} to the plugin a file came from. Codex and the other
harnesses export it as plugins/neva-core for everything, library files included. So a library
file never writes a path under the root directly: it goes through this helper, which ships
byte-identical in both plugins at scripts/neva_core.py, so that one path holds under either root.
Standard library only.

    python3 neva_core.py library <relative path in neva-library>   print the absolute path
    python3 neva_core.py path <relative path in neva-core>         print the absolute path
    python3 neva_core.py run  <relative .py path in neva-core> [args...]

A plugin is looked up from this file's own plugin, first match wins:
  1. itself, when it is the plugin asked for
  2. NEVA_CORE_ROOT or NEVA_LIBRARY_ROOT, when it holds that plugin's plugin.json
  3. the sibling folder (a repo checkout or --plugin-dir)
  4. ../../<plugin>/<version>/ (the Claude Code plugin cache): the same version as this
     plugin first, else the highest version present
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CORE = "neva-core"
LIBRARY = "neva-library"
OVERRIDE = {CORE: "NEVA_CORE_ROOT", LIBRARY: "NEVA_LIBRARY_ROOT"}


def is_plugin(path, name):
    try:
        manifest = json.loads((Path(path) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return manifest.get("name") == name


def version_key(path):
    return [int(part) if part.isdigit() else -1 for part in path.name.split(".")]


def locate(name, start, env):
    if is_plugin(start, name):
        return start.resolve()
    override = env.get(OVERRIDE[name])
    if override and is_plugin(override, name):
        return Path(override).resolve()
    sibling = start.parent / name
    if is_plugin(sibling, name):
        return sibling.resolve()
    cache = start.parent.parent / name
    if cache.is_dir():
        same = cache / start.name
        if is_plugin(same, name):
            return same.resolve()
        versions = sorted((p for p in cache.iterdir() if is_plugin(p, name)), key=version_key, reverse=True)
        if versions:
            return versions[0].resolve()
    raise SystemExit("neva_core: " + name + " not found beside " + str(start) + ". Install it (claude plugin "
                     + "install " + name + "@neva) or set " + OVERRIDE[name] + " to its plugin folder.")


def core_root(start=HERE, env=None):
    return locate(CORE, start, os.environ if env is None else env)


def library_root(start=HERE, env=None):
    return locate(LIBRARY, start, os.environ if env is None else env)


def inside(root, rel):
    if not rel or os.path.isabs(rel) or ".." in Path(rel).parts:
        raise SystemExit("neva_core: " + repr(rel) + " must be a relative path inside the plugin, without '..'.")
    target = (root / rel).resolve()
    if root not in target.parents or not target.exists():
        raise SystemExit("neva_core: " + rel + " does not exist in " + str(root) + ".")
    return target


def main(argv):
    if len(argv) < 2 or argv[0] not in ("library", "path", "run"):
        raise SystemExit("usage: neva_core.py library <path> | path <path> | run <script.py> [args...]")
    target = inside(library_root() if argv[0] == "library" else core_root(), argv[1])
    if argv[0] != "run":
        print(target)
        return 0
    if target.suffix != ".py":
        raise SystemExit("neva_core: run takes a .py script, got " + argv[1] + ".")
    os.execv(sys.executable, [sys.executable, str(target)] + argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
