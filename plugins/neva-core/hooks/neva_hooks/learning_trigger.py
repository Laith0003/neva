# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""neva_hooks.learning_trigger: same-day SessionEnd trigger for continuous-learning-v2.

Fires instinct-analyze.py in the background, outside its nightly timer, once enough new
observations have piled up since the analyze lock was last touched by a real run. The trigger
itself only decides and returns: it never runs the analysis inline. Before launching it probes
the same lock instinct-analyze.py takes at startup and skips when a run already holds it. The
probe is released before the launch, so two SessionEnds in the same instant can both launch;
single flight is guaranteed by instinct-analyze.py itself, which exits at once when it cannot
take that lock. The probe only saves the wasted process in the common case.

Off unless the owner opts in. Every launch runs `claude --print` per qualifying project bucket,
which spends model credit and writes instinct notes, so the trigger fails closed: with
NEVA_INSTINCT_SAMEDAY unset or anything other than exactly "1" it returns before reading a
single file. Declining the nightly timer at install time therefore also means no same-day run.

Env vars:
  NEVA_INSTINCT_SAMEDAY        "1" turns the trigger on. Any other value, or unset: off.
  NEVA_INSTINCT_SAMEDAY_MIN    observations pending in analysis-eligible project buckets needed to
                               fire. Default 200. A bucket is eligible only when it holds at least
                               the analyzer's own minimum (NEVA_INSTINCT_MIN_OBSERVATIONS, else
                               analyze.min_observations_to_analyze in config.json, else 20), so the
                               trigger never launches a run that would skip every bucket.
  NEVA_INSTINCT_SAMEDAY_HOURS  hours that must have passed since the lock file's mtime (the last
                               real analyze attempt) before firing again. Default 6.
  NEVA_HEADLESS                any truthy value: no-op. dispatch.py already skips every hook
                               module when this is set; checked again here for direct callers.
"""
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

from . import common as c

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover
    _HAS_FCNTL = False

HOOKS_DIR = Path(__file__).resolve().parent.parent
CL2_DIR = HOOKS_DIR.parent / "skills" / "continuous-learning-v2"
ANALYZE = CL2_DIR / "scripts" / "instinct-analyze.py"
CL2_CONFIG = CL2_DIR / "config.json"
LEARNING_IO = CL2_DIR / "scripts" / "learning_io.py"

DEFAULT_MIN_OBSERVATIONS = 200
DEFAULT_SAMEDAY_HOURS = 6.0
DEFAULT_ANALYZER_MIN = 20
_CHUNK = 1 << 16


def _analyzer_min() -> int:
    """The per-bucket minimum instinct-analyze.py applies, resolved the way its load_config
    does: a valid NEVA_INSTINCT_MIN_OBSERVATIONS, else config.json, else 20."""
    try:
        return int(c.env("NEVA_INSTINCT_MIN_OBSERVATIONS").strip())
    except ValueError:
        pass
    try:
        with open(CL2_CONFIG, encoding="utf-8") as fh:
            return int(json.load(fh)["analyze"]["min_observations_to_analyze"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_ANALYZER_MIN


def _count_lines(path: Path, stop_at: int) -> int:
    """Lines in `path`, but stop reading as soon as `stop_at` is reached, so SessionEnd never
    reads a whole 10 MB observations file just to compare it with a small threshold."""
    n = 0
    with open(path, "rb") as fh:
        while n < stop_at:
            block = fh.read(_CHUNK)
            if not block:
                break
            n += block.count(b"\n")
    return min(n, stop_at)


def _bucket_count(sources: list, stop_at: int) -> int:
    """Lines across one bucket's sources (rotated pending files plus the live file), stopping
    once `stop_at` is reached."""
    n = 0
    for src in sources:
        if n >= stop_at:
            break
        try:
            n += _count_lines(src, stop_at=stop_at - n)
        except OSError:
            continue
    return n


def _enough_eligible_observations(minimum: int) -> bool:
    """True when the buckets instinct-analyze.py would actually analyze (at least its own
    per-bucket minimum) hold `minimum` observations between them. Same directory resolution
    as the hook runtime and the nightly job (neva_hooks/common.py observations_dir), and the
    analyzer's own source discovery (learning_io.observation_sources), so rotated files in
    observations.pending count exactly as the analyzer reads them."""
    root = Path(c.observations_dir())
    analyzer_min = max(1, _analyzer_min())
    total = 0
    try:
        sources_of = _learning_io().observation_sources
        pid_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    except Exception:  # learning_io missing or the root unreadable: never launch blind
        return False
    for pid_dir in pid_dirs:
        need = max(analyzer_min, minimum - total)
        n = _bucket_count(sources_of(pid_dir), stop_at=need)
        if n >= analyzer_min:
            total += n
            if total >= minimum:
                return True
    return False


def _learning_io():
    """The analyzer's own learning_io module, loaded by path: it ships with the skill, not
    with the hooks package, and its name must not collide with anything on sys.path."""
    spec = importlib.util.spec_from_file_location("neva_learning_io", LEARNING_IO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hours_since(lock_path: Path) -> float:
    try:
        mtime = lock_path.stat().st_mtime
    except OSError:
        return float("inf")  # never run before: treat as arbitrarily stale
    return (time.time() - mtime) / 3600.0


def _try_lock(lock_path: Path):
    """Non-blocking flock on the same file instinct-analyze.py locks at startup. Opened with
    create-never-truncate so a successful probe does not disturb the mtime the hours check
    reads, and through learning_io so a symlinked lock is refused (ManagedPathError) rather than
    followed out of the state root. Returns the open fd on success, None if another run already
    holds it."""
    if not _HAS_FCNTL:
        return None
    fd = _learning_io().open_lock(lock_path.parent, lock_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        return None
    return fd


def _unlock(fd) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()


def opted_in() -> bool:
    """Exactly "1" and nothing else, so a typo or "true" never starts a paid job."""
    return c.env("NEVA_INSTINCT_SAMEDAY").strip() == "1"


def run(ctx):
    if not opted_in():
        return None
    if c.env_flag("NEVA_HEADLESS"):
        return None
    minimum = c.env_int("NEVA_INSTINCT_SAMEDAY_MIN", DEFAULT_MIN_OBSERVATIONS, lo=1)
    try:
        hours = float(c.env("NEVA_INSTINCT_SAMEDAY_HOURS") or DEFAULT_SAMEDAY_HOURS)
    except ValueError:
        hours = DEFAULT_SAMEDAY_HOURS

    if not _enough_eligible_observations(minimum):
        return None

    lock_path = Path(c.state_root()) / "instinct-analyze.lock"
    if _hours_since(lock_path) <= hours:
        return None

    try:
        fd = _try_lock(lock_path)
    except Exception as exc:  # ManagedPathError, or learning_io missing: never launch blind
        c.log(f"[learning_trigger] same-day trigger skipped: {exc}")
        return None
    if fd is None:
        c.log("[learning_trigger] previous instinct-analyze run still active; same-day trigger skipped")
        return None
    _unlock(fd)

    if not ANALYZE.exists():
        c.log(f"[learning_trigger] {ANALYZE} not found; same-day trigger skipped")
        return None
    try:
        subprocess.Popen([sys.executable, str(ANALYZE)], cwd=str(ANALYZE.parent),
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
        c.log("[learning_trigger] same-day threshold reached; fired instinct-analyze.py")
    except OSError as exc:
        c.log(f"[learning_trigger] failed to launch instinct-analyze.py: {exc!r}")
    return None
