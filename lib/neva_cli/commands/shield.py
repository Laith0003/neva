"""neva shield: scan agent harness configuration for security problems."""
import os
import sys
from pathlib import Path

from neva_shield import SEVERITY_RANK, render, scan_machine, scan_path
from neva_shield.redact import redact

HELP = "scan agent harness configuration for security problems"
FORMATTERS = {"text": render.text, "json": render.json_text, "sarif": render.sarif}


def add_arguments(parser):
    parser.add_argument("--path", metavar="DIR",
                        help="scan one repository checkout (CI mode) instead of this machine")
    parser.add_argument("--machine", action="store_true",
                        help="scan every harness configuration in this home directory (the default)")
    parser.add_argument("--format", choices=("text", "json", "sarif"), default="text",
                        help="text for humans, json for tooling, sarif for GitHub code scanning")
    parser.add_argument("--fail-on", choices=("high", "medium"), default="high",
                        help="exit 1 when a finding reaches this severity (default: high)")
    parser.add_argument("--show-paths", action="store_true",
                        help="machine scans only: print real project, skill and server names instead of labels")
    parser.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")


def run(args):
    if args.machine and args.path:
        print("shield: --machine and --path are mutually exclusive. Pass one of them.", file=sys.stderr)
        return 2
    if args.show_paths and args.path:
        print("shield: --show-paths applies to machine scans. Repository scans already print relative paths.", file=sys.stderr)
        return 2
    try:
        result = scan_path(args.path) if args.path else scan_machine(show_paths=args.show_paths)
    except (ValueError, RuntimeError) as exc:
        print("shield: " + redact(str(exc)), file=sys.stderr)
        return 2
    except OSError as exc:
        print("shield: could not read the scan target: " + redact(str(exc)), file=sys.stderr)
        return 2

    report = FORMATTERS[args.format](result)
    if args.out:
        try:
            root = Path(os.path.expandvars(args.path)).expanduser() if args.path else Path.cwd()
            _write_report(args.out, root, report + "\n")
        except (OSError, ValueError) as exc:
            print("shield: --out could not be written: " + redact(str(exc)), file=sys.stderr)
            return 2
        print("shield: wrote " + args.format + " report to " + redact(args.out), file=sys.stderr)
    else:
        print(report)
    if result.empty:
        print("shield: no harness configuration found under " + result.root
              + ", so nothing was checked. Point --path at a repository with agent configuration.",
              file=sys.stderr)
        return 2
    return 1 if result.worst_rank() >= SEVERITY_RANK[args.fail_on] else 0


def _write_report(destination, root, report):
    """Create a new report inside the scan root (cwd for machine scans).

    Traverse from / using directory descriptors and O_NOFOLLOW. Exclusive creation
    refuses existing files, including scanned inputs and hard links, without truncation.
    Each descriptor pins its directory even if its pathname changes during the write.
    """
    root = root.absolute()
    target = Path(os.path.expandvars(destination)).expanduser().absolute()
    for path in (root, target):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("report path contains a symlink; choose a real directory and a new filename")
    real_root = root.resolve(strict=True)
    try:
        target.resolve().relative_to(real_root)
    except ValueError as exc:
        raise ValueError("--out is outside the report root; choose a new filename inside the scan root") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(target.anchor, flags)
    try:
        for part in target.parts[1:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(report)
    finally:
        os.close(directory)
