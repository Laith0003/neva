"""One snapshot of everything the cockpit shows, shared by --json, the TUI and the web view, so
the three can never disagree about what a health row or a hook error says."""
from . import health, ingest

NOTES_SHOWN = 20
HEALTH_KEYS = ("scheduled_jobs", "omniroute", "pending_proposals", "nightly")


def health_rows(snap_health):
    """[{"name", "ok", "detail"}] in display order, with a detail line for every row."""
    rows = []
    for key in HEALTH_KEYS:
        info = snap_health.get(key) or {}
        ok = bool(info.get("ok"))
        if ok and key == "pending_proposals":
            detail = f"{info.get('count', 0)} pending"
        elif ok and key == "scheduled_jobs":
            jobs = info.get("jobs") or []
            failing = [j.get("label", "") for j in jobs
                       if str(j.get("last_exit_status", "0")) not in ("0", "-")]
            detail = f"{len(jobs)} job(s) loaded"
            if failing:
                detail += ", last exit nonzero: " + ", ".join(failing)
        else:
            detail = str(info.get("detail", "") or ("no result" if not info else ""))
        rows.append({"name": key, "ok": ok, "detail": detail})
    return rows


def build(store, refresh=False, health_fn=None):
    """refresh=True runs an incremental ingest first, so a long-running view stays live."""
    if refresh:
        ingest.ingest_all(store)
    snap_health = (health_fn or health.snapshot)()
    return {
        "sessions": store.sessions(),
        "health": snap_health,
        "health_rows": health_rows(snap_health),
        "hook_errors": store.recent_notes("hook-error", NOTES_SHOWN),
        "rejected_rows": store.recent_notes("rejected-row", NOTES_SHOWN),
    }
