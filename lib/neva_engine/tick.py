"""One look: read every source, run the rules, gate the output, write today.json. Run it from launchd.

Exit 0 when every read worked, 1 when a source failed (the rest still ran and today.json says which), 2 when the run
could not start safely and wrote nothing, 3 when a denied term survived to the final check and nothing was written."""
from __future__ import annotations

import datetime
import json
import os
import sys

from . import collectors, rules, today as today_mod
from .gate import Deny, Gate
from .model import ConfigError, Denied, ShapeError, SourceRead
from .store import RETENTION_DAYS, Store, ensure_private_dir
from .today import DENIED_ERROR


def load_config(path):
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise ConfigError(f"config {path}: cannot read it ({e}). Fix the file.")
    for key in ("root", "runtime", "sources", "deny_file"):
        if key not in cfg:
            raise ConfigError(f"config {path}: no `{key}`. Add it; `deny_file` may be null for no list.")
    return cfg


def read_source(name, cfg, deny, day):
    reader = collectors.Reader(cfg["root"], deny)

    def stopped(status, text):
        """Error text is output: it can quote a line. One with a denied term becomes the generic words."""
        return SourceRead(name, status, error=DENIED_ERROR if deny.hit(text) else text, denied=reader.denied)
    try:
        facts = collectors.COLLECTORS[name](cfg["sources"][name], reader, day)
    except Denied:
        return SourceRead(name, "failed", error=DENIED_ERROR, denied=reader.denied)
    except ShapeError as e:
        return stopped("failed", str(e))
    except FileNotFoundError as e:
        return stopped("absent", f"{e.filename or e}: not found. Unknown, not zero.")
    except (OSError, UnicodeDecodeError) as e:
        return stopped("failed", f"{name}: {e}. Check the file.")
    except Exception as e:  # one bad source never stops the look; the rest still run and the failure is shown
        return stopped("failed", f"{name}: {type(e).__name__}: {e}.")
    kept = [f for f in facts if not deny.hit(f"{f.subject}\n{f.quote}\n{json.dumps([f.value, f.memo], ensure_ascii=False)}")]
    return SourceRead(name, "ok" if kept else "proven_empty", kept, reader.first_path, reader.first_hash,
                      denied=reader.denied + len(facts) - len(kept))


def write_private(path, text):
    tmp = f"{path}.tmp{os.getpid()}"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def run(config_path, now=None, dry_run=False, out=None):
    now = now or datetime.datetime.now()
    try:
        cfg = load_config(config_path)
        deny = Deny.load(cfg["deny_file"])
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    runtime = os.path.expanduser(out or cfg["runtime"])
    day = (now - datetime.timedelta(hours=cfg.get("day_rollover_hour", 0))).date()
    reads = {name: read_source(name, cfg, deny, day) for name in collectors.COLLECTORS if name in cfg["sources"]}
    facts = [f for r in reads.values() for f in r.facts]
    usable = {name for name, r in reads.items() if r.status in ("ok", "proven_empty")}
    probe = collectors.Reader(cfg["root"], deny)
    gate = Gate(probe.allowed, day)
    store = None if dry_run else Store(runtime)
    last = store.last_look() if store else None
    looked = now.isoformat(timespec="seconds")
    gap = None
    if last:
        gap = round((now - datetime.datetime.fromisoformat(last)).total_seconds() / 3600, 1)
        gap = int(gap) if gap == int(gap) else gap
    cards, errors = rules.evaluate(facts, usable, cfg.get("rules", {}), day)
    kept, today = today_mod.build(reads, facts, cards, errors, gate, deny, now, day, gap)
    text = json.dumps(today, ensure_ascii=False, indent=1) + "\n"
    if deny.hit(text):
        print("today.json: a denied term reached the final check. Nothing was written.", file=sys.stderr)
        if store:
            store.close()
        return 3
    if dry_run:
        print(text, end="")
    else:
        for read in reads.values():
            store.record(read, looked)
        for card in kept:
            store.candidate(card, looked)
        store.prune((now - datetime.timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds"))
        store.close()
        ensure_private_dir(runtime)
        write_private(os.path.join(runtime, "today.json"), text)
    return 1 if errors or any(r.status == "failed" for r in reads.values()) else 0
