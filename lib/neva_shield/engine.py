"""Scan orchestration for Neva Shield. Standard library only.

Two entry points. scan_path walks one repository, which is the CI mode. scan_machine
walks the named harness locations in a home directory, which is the local audit mode and
never walks the whole home tree.
"""
import os
import re
from pathlib import Path

from . import collect, printer as printers
from .model import Finding, ScanResult, merge
from .rules import FAMILIES
from .redact import credential_values, redact

# Home locations that hold agent harness configuration, with the walk depth each needs.
# Depth is bounded so a machine scan stays fast and never descends into unrelated trees.
MACHINE_TARGETS = (
    (".claude", None),
    (".codex", None),
    (".config/opencode", None),
    (".cursor", 3),
    (".gemini", 3),
    (".config/github-copilot", 2),
)
MACHINE_FILES = (".claude.json", ".cursorrules")
# Project configuration under the code home: <root>/<venture>/<repo>/.claude/settings.json.
DEFAULT_PROJECT_ROOTS = ("Code", "code")
PROJECT_DEPTH = 3


def project_roots():
    """Directories under home that hold checkouts. NEVA_SHIELD_PROJECT_ROOTS overrides."""
    override = os.environ.get("NEVA_SHIELD_PROJECT_ROOTS", "").strip()
    if override:
        return tuple(item for item in override.split(os.pathsep) if item)
    return DEFAULT_PROJECT_ROOTS


def _scan_sources(root, sources, printer):
    findings = []
    scanned = 0
    suppressed = 0
    for source in sources:
        source.toml() if source.path.suffix.lower() == ".toml" else source.data()
        secrets = credential_values(source)
        scanned += 1
        for name, family in FAMILIES:
            if not source.has(*family.KINDS):
                continue
            collected = []
            try:
                family.check(source, lambda *item: collected.append(item))
            except (OSError, ValueError, TypeError, re.error) as exc:
                raise collect.SafeError("shield rule family " + name + " failed on " + source.display + " with " + type(exc).__name__ + "; report this as a Shield bug") from exc
            for rule_id, severity, line, message, fix in collected:
                line = max(1, int(line))
                if source.is_suppressed(line, rule_id):
                    suppressed += 1
                    continue
                findings.append(Finding(rule_id, severity, redact(source.display, secrets), line,
                                        redact(printer.finish(message), secrets), redact(printer.finish(fix), secrets)))
    return ScanResult(root=str(root), findings=findings, files_scanned=scanned, suppressed=suppressed)


def scan_path(path, home=None):
    """Scan one directory tree, the way CI scans a repository checkout."""
    root = Path(os.path.expandvars(str(path))).expanduser()
    if not collect.safe_path(root, root):
        raise ValueError("--path contains a symlink; choose a real directory")
    if not root.is_dir():
        raise ValueError("--path must name an existing directory, got: " + str(path))
    root = root.resolve()
    # Shield's own fixtures are deliberately malicious. They are excluded from a scan of
    # the tree that contains them, and only from that, so scanning a fixture directly works.
    fixtures = root / "lib" / "neva_shield" / "tests" / "fixtures"
    skip = [fixtures] if fixtures.is_dir() else []
    home = Path(home) if home else Path.home()
    plain = collect.Plain(root, home)
    try:
        return merge(".", [_scan_sources(root, collect.sources(root, home=home, skip=skip, printer=plain), plain)])
    except collect.ScanError as exc:
        raise ValueError(exc.shown(plain)) from None


def scan_machine(home=None, show_paths=False):
    """Scan the harness configuration of one machine: every supported agent, no home walk."""
    home = Path(home).expanduser() if home else Path.home()
    if not collect.safe_path(home, home):
        raise ValueError("home contains a symlink; choose a real home directory")
    home = home.resolve()
    printer = printers.Shown(home) if show_paths else printers.Private(home, project_roots())
    try:
        return merge("~", _machine_results(home, printer))
    except collect.ScanError as exc:
        raise ValueError(exc.shown(printer)) from None
    except (ValueError, RuntimeError, OSError) as exc:
        raise ValueError(printer.error(exc)) from None


def _link_finding(path, row, home, printer):
    origin, target, whole = row
    severity = collect.link_severity(path, origin, target, home, whole)
    shown = printer.path(path)
    if severity == "low":
        rule = "LINK002"
    else:
        rule = "LINK001"
    return Finding(rule, severity, redact(shown), 1,
                   "Symlink " + shown + " was not followed, so Shield did not read what the harness loads through it.",
                   "Scan the link target with neva shield --path on the real directory, or replace the link with a real file or directory.")


def _machine_results(home, printer):
    results = []
    log = collect.LinkLog()
    for relative, depth in MACHINE_TARGETS:
        target = home / relative
        link = collect.first_link(target, home)
        if link is not None:
            log.add(link, "home", target, whole=True)
            continue
        collect.require_safe_path(target, home)
        collect.reject_special(target)
        if target.is_dir():
            links = log.scoped("home", target)
            results.append(_scan_sources(home, _home_sources(target, home, depth, links, printer), printer))
    singles = []
    for relative in MACHINE_FILES:
        item = home / relative
        link = collect.first_link(item, home)
        if link is not None:
            log.add(link, "home", item, whole=True)
            continue
        collect.require_safe_path(item, home)
        collect.reject_special(item)
        singles.append(item)
    results.append(_scan_sources(home, _single_sources([item for item in singles if item.is_file()], home, printer), printer))
    # Compare by identity: on a case insensitive filesystem ~/Code and ~/code are one directory,
    # resolve() keeps the spelling it was given, and scanning both reports everything twice.
    walked = []
    for relative in project_roots():
        target = home / relative
        link = collect.first_link(target, home)
        if link is not None:
            log.add(link, "project", target, whole=True)
            continue
        collect.require_safe_path(target, home)
        if not target.is_dir():
            continue
        if any(os.path.samefile(target, item) for item in walked):
            continue
        walked.append(target)
        links = log.scoped("project", target)
        results.append(_scan_sources(home, collect.project_sources(target, home, PROJECT_DEPTH, links, printer), printer))
    findings = [_link_finding(path, row, home, printer) for path, row in sorted(log.rows.items())]
    skipped = sum(1 for row in log.rows.values() if row[2])
    results.append(ScanResult(root="~", findings=findings, skipped_targets=skipped))
    return results


def _home_sources(target, home, depth, links, printer):
    """Sources under one home location, classified and displayed against the home root."""
    return collect.sources(target, home=home, max_depth=depth, relative_to=home, display_root=home,
                           links=links, printer=printer)


def _single_sources(paths, home, printer):
    for path in paths:
        kinds = collect.classify(path, (path.name,))
        read = collect.read_file(path)
        if not kinds or read is None:
            continue
        text, mode = read
        yield collect.Source(path, printer.path(path), kinds, text, mode, printer)
