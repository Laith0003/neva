# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Name what is broken in a Neva install and exactly how to fix it.

Two halves. The vault half shells out to bin/doctor, which has checked the brain side since
long before there was a CLI. The harness half is new: every entry the install-state manifest
owns is compared against the checksum recorded when Neva wrote it, then the things a manifest
cannot see are checked directly, the hook registration, the rules, the env, the nightly
command and the scheduled jobs.

Every FAIL row names its fix. The exit code is 1 when anything failed, 0 otherwise. A WARN is
something worth knowing that does not mean the install is broken, so it never fails the run.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from neva_cli import core

HELP = "check Neva vault and harness installation health"


def add_arguments(parser):
    parser.add_argument("--harness", help="check one installed harness instead of all of them")
    parser.add_argument("--no-vault", action="store_true", help="skip the bin/doctor vault checks")


class Report:
    def __init__(self):
        self.failures = 0

    def row(self, status, label, fix=""):
        print("  " + status.ljust(4) + " " + label + (("  fix: " + fix) if fix else ""))
        if status == "FAIL":
            self.failures += 1

    def ok(self, label):
        self.row("OK", label)

    def fail(self, label, fix):
        self.row("FAIL", label, fix)

    def warn(self, label, fix=""):
        self.row("WARN", label, fix)


def run_vault_doctor(report):
    if os.environ.get("NEVA_SKIP_VAULT_DOCTOR") == "1":
        report.row("SKIP", "vault doctor skipped by NEVA_SKIP_VAULT_DOCTOR")
        return
    script = core.REPO_ROOT / "bin" / "doctor"
    if not script.is_file():
        report.fail("vault doctor missing at " + str(script), "restore bin/doctor from the template")
        return
    result = subprocess.run([str(script)], text=True, capture_output=True)
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output)
    if result.returncode:
        report.fail("vault doctor reported failures", "fix the rows bin/doctor printed above")
    else:
        report.ok("vault doctor clean")


def check_entries(report, harness, entries):
    broken = []
    for entry in entries:
        try:
            current = core.entry_checksum(entry)
        except (OSError, ValueError) as error:
            broken.append((entry, str(error)))
            continue
        if current is None:
            broken.append((entry, "missing"))
        elif current != entry.get("checksum"):
            broken.append((entry, "modified"))
    for entry, detail in broken:
        label = harness + " entry " + detail + ": " + entry["dest"]
        if entry.get("key"):
            label += " [" + entry["key"] + "]"
        report.fail(label, "run neva repair --harness " + harness)
    if not broken:
        report.ok(harness + ": " + str(len(entries)) + " managed entries present and unmodified")


def check_hooks(report):
    hooks_dir = core.REPO_ROOT / "plugins" / "neva-core" / "hooks"
    dispatch = hooks_dir / "dispatch.py"
    if not dispatch.is_file():
        report.fail("Claude hook dispatcher missing at " + str(dispatch),
                    "restore plugins/neva-core/hooks/dispatch.py from the template")
        return
    try:
        registered = set(json.loads((hooks_dir / "hooks.json").read_text(encoding="utf-8"))["hooks"])
        meta = json.loads((hooks_dir / "hooks.meta.json").read_text(encoding="utf-8"))
        modules = meta["modules"] if isinstance(meta, dict) and "modules" in meta else meta
        wanted = {event for module in modules for event in module.get("events", [])}
    except (OSError, ValueError, KeyError, TypeError) as error:
        report.fail("Claude hook registration unreadable: " + str(error),
                    "repair plugins/neva-core/hooks/hooks.json and hooks.meta.json")
        return
    missing = sorted(wanted - registered)
    if missing:
        report.fail("hook events with modules but no registration: " + ", ".join(missing),
                    "add those events to plugins/neva-core/hooks/hooks.json")
    else:
        report.ok("every hook module's event is registered in hooks.json")
    try:
        result = probe_dispatcher(dispatch)
    except (OSError, subprocess.TimeoutExpired) as error:
        report.fail("Claude hook dispatcher could not run: " + str(error),
                    "run python3 plugins/neva-core/hooks/dispatch.py SessionStart and read the error")
        return
    if result.returncode:
        report.fail("Claude hook dispatcher exited " + str(result.returncode),
                    "run python3 plugins/neva-core/hooks/dispatch.py SessionStart and read the error")
    else:
        report.ok("Claude hook dispatcher runs")


def probe_dispatcher(dispatch):
    """Run the SessionStart dispatcher once in a disposable HOME, so the check has no effects.

    The real hooks write state (project cache, session files) and read the vault. A health check
    must do neither: every NEVA_* and XDG_* variable is dropped, HOME, the state and data
    directories and the working directory all point into a temporary directory that is removed
    afterwards, and bytecode is never written next to the dispatcher.
    """
    with tempfile.TemporaryDirectory(prefix="neva-doctor-probe-") as scratch:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("NEVA_", "XDG_", "CLAUDE_"))}
        env.update({"HOME": scratch, "NEVA_STATE_DIR": os.path.join(scratch, "state"),
                    "NEVA_DATA_DIR": os.path.join(scratch, "data"),
                    "NEVA_CONFIG": os.path.join(scratch, "identity.env"),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        return subprocess.run([sys.executable, "-B", str(dispatch), "SessionStart"],
                              input='{"hook_event_name":"SessionStart","source":"startup"}',
                              text=True, capture_output=True, env=env, cwd=scratch, timeout=60)


def check_rules(report, entries):
    rules = [entry for entry in entries
             if entry.get("kind") == "copy" and "/rules/neva/" in entry.get("dest", "")]
    if not rules:
        report.fail("no Claude rules recorded in the install-state manifest",
                    "run neva install --harness claude --yes")
        return
    absent = [entry["dest"] for entry in rules if not Path(entry["dest"]).is_file()]
    if absent:
        report.fail(str(len(absent)) + " Claude rules missing, first: " + absent[0],
                    "run neva repair --harness claude")
    else:
        report.ok(str(len(rules)) + " Claude rules present under ~/.claude/rules/neva/")


def check_env(report, record=None):
    settings = core.home() / ".claude" / "settings.json"
    if record is not None and record.get("claude_settings") is False:
        report.ok("Claude settings left unchanged at install (--no-claude-settings); set NEVA_* in " +
                  str(settings) + " yourself if you want them")
        return
    try:
        env = core.lookup(core.read_json_object(settings), "env", {})
    except ValueError as error:
        report.fail("Claude settings unreadable: " + str(error), "correct the file it names")
        return
    missing = [name for name in ("NEVA_HOOK_PROFILE", "NEVA_PLUGINS")
               if not (isinstance(env, dict) and env.get(name))]
    if missing:
        report.fail("Claude settings env missing " + ", ".join(missing) + " in " + str(settings),
                    "run neva install --harness claude --yes")
    else:
        report.ok("Claude settings env has NEVA_HOOK_PROFILE=" + env["NEVA_HOOK_PROFILE"] +
                  " and NEVA_PLUGINS=" + env["NEVA_PLUGINS"])


def check_marketplace(report):
    binary = core.find_binary("claude")
    if not binary:
        report.warn("claude CLI not on PATH, plugin marketplace not inspected",
                    "install Claude Code, then run neva doctor again")
        return
    try:
        marketplaces, _ = core.claude_registered(binary)
    except ValueError as error:
        report.fail("cannot list Claude Code registrations: " + str(error),
                    "run claude plugin marketplace list yourself and correct what it names")
        return
    if "neva" in marketplaces:
        report.ok("the neva plugin marketplace is registered with Claude Code")
    else:
        report.warn("the neva plugin marketplace is not registered with Claude Code",
                    "run claude plugin marketplace add " + str(core.REPO_ROOT))


def check_claude_runtime(report):
    binary = os.environ.get("NEVA_CLAUDE_BIN") or core.find_binary("claude")
    if binary and Path(binary).exists():
        report.ok("nightly Claude command available at " + binary)
    else:
        report.fail("nightly Claude command missing, so the instinct job cannot run",
                    "install Claude Code, or set NEVA_CLAUDE_BIN to its path")


def check_jobs(report):
    if sys.platform == "darwin":
        tool = shutil.which("launchctl")
        if not tool:
            report.warn("launchctl not on PATH, scheduled jobs not inspected")
            return
        command = [tool, "print", "gui/" + str(os.getuid()) + "/com.neva.cadence"]
    else:
        tool = shutil.which("systemctl")
        if not tool:
            report.warn("systemctl not on PATH, scheduled jobs not inspected")
            return
        command = [tool, "--user", "is-enabled", "neva-cadence.timer"]
    if subprocess.run(command, capture_output=True).returncode == 0:
        report.ok("the Neva scheduled job is loaded")
    else:
        report.warn("the Neva scheduled job is not loaded",
                    "enable it one job at a time, see docs/03-scheduled-jobs.md")


@core.reports_refusals
def run(args):
    report = Report()
    if not args.no_vault:
        print("vault doctor")
        run_vault_doctor(report)
    state = core.load_state()
    harnesses = state.get("harnesses", {})
    names = [args.harness] if args.harness else sorted(harnesses)
    print("harness doctor")
    if not names:
        report.fail("no harness install state at " + str(core.state_path()),
                    "run neva install --harness claude --yes")
        return 1
    for harness in names:
        if harness not in harnesses:
            report.fail(harness + " is not installed", "run neva install --harness " + harness + " --yes")
            continue
        entries = [entry for entry in state.get("entries", []) if entry.get("harness") == harness]
        check_entries(report, harness, entries)
        if harness == "claude":
            check_rules(report, entries)
            check_env(report, harnesses.get("claude"))
            check_hooks(report)
            check_marketplace(report)
            check_claude_runtime(report)
            check_jobs(report)
    return 1 if report.failures else 0
