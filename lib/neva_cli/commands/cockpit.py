"""neva cockpit: a read-only dashboard over what the hooks runtime already writes.

Ingests the latest session summaries, costs, observations and codex sessions into the cockpit's
sqlite store, then shows them: as a curses TUI by default, as one JSON snapshot with --json, or
as a local read-only web view (127.0.0.1 only, token in the path) with --web.

The cockpit package is imported inside run(), not at module load: bin/neva imports every
command to build its help, so a cockpit that cannot start must not take `neva --help` and every
other command down with it.
"""
import json
import sys

HELP = "show Neva session, cost and health status (TUI, --json, or --web)"


def add_arguments(parser):
    parser.add_argument("--json", action="store_true",
                        help="print one JSON snapshot to stdout and exit, instead of the TUI")
    parser.add_argument("--web", action="store_true",
                        help="serve a read-only local web view instead of the TUI")


def run(args):
    try:
        from neva_cockpit import ingest, snapshot, ui, web
        from neva_cockpit.store import Store
    except ImportError as error:
        if type(error).__name__ != "HooksRuntimeMissing":
            raise  # a real bug keeps its traceback; only the known layout gap is one line
        print(str(error), file=sys.stderr)
        return 2
    store = Store()
    try:
        ingest.ingest_all(store)
        if args.json:
            print(json.dumps(snapshot.build(store)))
            return 0
        # The long-running views ingest again at every refresh, so a session, cost or risk
        # written after start shows up without a restart.
        live = lambda: snapshot.build(store, refresh=True)  # noqa: E731
        if args.web:
            web.serve(snapshot_fn=live)
            return 0
        return ui.run(store=store, snapshot_fn=live)
    finally:
        store.close()
