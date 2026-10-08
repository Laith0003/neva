# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Show which harnesses are on this machine, which ones Neva installed into, and with what."""
from neva_cli import core
from neva_cli.commands.install import all_harnesses

HELP = "list detected harnesses, installed harnesses, and enabled plugins"


def add_arguments(parser):
    parser.add_argument("--installed", action="store_true", help="list only the installed harnesses")


def detection(harness):
    """(detected, note). note explains a 'no' that is not simply 'the harness is absent'."""
    if harness == "claude":
        return bool(core.find_binary("claude")), ""
    try:
        contract, path = core.read_adapter(harness)
    except core.AdapterError as error:
        return False, "adapter unusable: " + str(error)
    if contract is None:
        return False, "no adapter at " + str(path)
    return core.detected(contract), ""


@core.reports_refusals
def run(args):
    state = core.load_state()
    installed = state.get("harnesses", {})
    names = sorted(installed) if args.installed else all_harnesses()
    if not names:
        print("no harnesses" + (" installed" if args.installed else " known") +
              ". fix: run neva install --harness claude --yes")
        return 0
    for harness in names:
        found, note = detection(harness)
        detail = installed.get(harness, {})
        fields = ["detected=" + ("yes" if found else "no"),
                  "installed=" + ("yes" if harness in installed else "no")]
        if harness in installed:
            fields.append("plugins=" + (",".join(detail.get("plugins", [])) or "none"))
            fields.append("profile=" + str(detail.get("profile", "unknown")))
            fields.append("entries=" + str(sum(1 for entry in state.get("entries", [])
                                               if entry.get("harness") == harness)))
        if note:
            fields.append(note)
        print(harness + ": " + ", ".join(fields))
    return 0
