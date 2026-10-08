"""Health probes for the cockpit: scheduled jobs, OmniRoute, pending lessons, the nightly job.

Every probe returns a dict with at least {"ok": bool, "detail": str}. A probe that cannot
answer returns ok: False and a detail naming exactly what failed, never an empty result: the
difference between "checked, nothing wrong" and "could not check" matters to whoever is reading
the cockpit. The OmniRoute key is read to build a request header and is never put into any
detail string, log line, or exception message this module raises.
"""
import http.client
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request

from . import hooks_common

TAIL_BYTES = 64 * 1024
OMNIROUTE_URL = "http://127.0.0.1:20128/v1/models"
OMNIROUTE_KEY_PATH = os.path.join(hooks_common.home(), ".omniroute", "neva-builder.key")
OMNIROUTE_TIMEOUT_S = 3
KEY_RE = re.compile(r"[\x21-\x7e]+")  # printable ASCII, no whitespace: safe in a header
JOB_PREFIXES = ("com.neva.",)  # Neva's own launchd namespace (services/launchd/*.tmpl)


def job_prefixes():
    """Neva's namespace plus any extra prefixes from local configuration: the environment
    variable NEVA_COCKPIT_JOB_PREFIXES, else COCKPIT_JOB_PREFIXES in the identity file. Both are
    comma-separated. A personal namespace belongs there, never in this tracked file."""
    raw = (hooks_common.env("NEVA_COCKPIT_JOB_PREFIXES")
           or hooks_common.load_config().get("COCKPIT_JOB_PREFIXES", ""))
    extra = [p.strip() for p in raw.split(",") if p.strip()]
    return JOB_PREFIXES + tuple(p for p in extra if p not in JOB_PREFIXES)


def _tail_text(path, limit=TAIL_BYTES):
    """The last `limit` bytes as text. Raises OSError: an unreadable file is a different
    failure from a file that lacks what the caller looks for, and must be reported as one."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - limit))
        data = fh.read()
    return data.decode("utf-8", "ignore")


# ---------------------------------------------------------------- scheduled jobs

def scheduled_jobs():
    """{"ok", "jobs": [{"label", "pid", "last_exit_status"}]} or {"ok": False, "detail"}."""
    if sys.platform != "darwin":
        return {"ok": False, "detail": f"launchctl probe is macOS-only; this machine reports {sys.platform}"}
    tool = shutil.which("launchctl")
    if not tool:
        return {"ok": False, "detail": "launchctl not found on PATH"}
    try:
        result = subprocess.run([tool, "list"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "detail": f"launchctl list failed to run: {error}"}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:300] or "no output on stdout or stderr"
        return {"ok": False, "detail": f"launchctl list exited {result.returncode}: {detail}"}
    jobs = []
    prefixes = job_prefixes()
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, status, label = (p.strip() for p in parts)
        if pid == "PID" and status == "Status":
            continue  # the header row
        if label.startswith(prefixes):
            jobs.append({"label": label, "pid": pid, "last_exit_status": status})
    return {"ok": True, "jobs": jobs}


# ---------------------------------------------------------------- OmniRoute

def omniroute_health(url=None, key_path=None, timeout=OMNIROUTE_TIMEOUT_S):
    url = url or OMNIROUTE_URL
    key_path = key_path or OMNIROUTE_KEY_PATH
    try:
        with open(key_path, encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError as error:
        return {"ok": False, "detail": f"OmniRoute key unreadable at {key_path}: {error.strerror or error}"}
    if not key:
        return {"ok": False, "detail": f"OmniRoute key file at {key_path} is empty. "
                                        "fix: write the key into it on one line"}
    if not KEY_RE.fullmatch(key):
        # Never sent: http.client would reject it with the whole header in the exception.
        return {"ok": False, "detail": f"OmniRoute key at {key_path} contains whitespace, a "
                                        "control character or a non-ASCII character. fix: "
                                        "rewrite the file with only the key, on one line"}
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = response.getcode()
    except urllib.error.HTTPError as error:
        return {"ok": False, "detail": f"OmniRoute at {url} returned HTTP {error.code}"}
    except socket.timeout:
        return {"ok": False, "detail": f"OmniRoute at {url} timed out after {timeout}s"}
    except urllib.error.URLError as error:
        return {"ok": False, "detail": f"OmniRoute at {url} unreachable: {error.reason}"}
    except (ValueError, OSError, http.client.HTTPException) as error:
        # The message of these can quote the request headers; report only the type.
        return {"ok": False, "detail": f"OmniRoute request to {url} failed with "
                                        f"{type(error).__name__}. fix: check the key file at "
                                        f"{key_path} and that OmniRoute is running"}
    if code != 200:
        return {"ok": False, "detail": f"OmniRoute at {url} returned HTTP {code}"}
    return {"ok": True, "detail": f"OmniRoute reachable at {url}"}


# ---------------------------------------------------------------- pending lesson proposals

def pending_proposals():
    if not hooks_common.vault_path():
        return {"ok": False, "detail": "no vault configured (NEVA_VAULT unset and no VAULT_PATH "
                                        "in the identity file); cannot count pending lesson proposals"}
    return {"ok": True, "count": len(hooks_common.open_proposal_files())}


# ---------------------------------------------------------------- last nightly result

def last_nightly_result(path=None):
    path = path or os.path.join(hooks_common.state_root(), "instinct-analyze.log")
    if not os.path.isfile(path):
        return {"ok": False, "detail": f"no nightly run recorded yet: {path} does not exist"}
    try:
        text = _tail_text(path)
    except OSError as error:
        return {"ok": False, "detail": f"nightly log {path} is unreadable: "
                                        f"{error.strerror or error}. fix: chmod u+r {path}, "
                                        "or check who owns it"}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    start_at = None
    for i in range(len(lines) - 1, -1, -1):
        if "] start (" in lines[i]:
            start_at = i
            break
    if start_at is None:
        return {"ok": False, "detail": f"no start marker found in the tail of {path}"}
    timestamp = lines[start_at].split("]", 1)[0].lstrip("[")
    since_start = lines[start_at:]
    if any(ln.endswith("] done") for ln in since_start):
        return {"ok": True, "detail": f"last nightly run started {timestamp} and finished"}
    if any("previous instinct-analyze run still active" in ln for ln in since_start):
        return {"ok": True, "detail": f"last nightly run at {timestamp} was skipped: a previous run was still active"}
    return {"ok": False, "detail": f"last nightly run started {timestamp} and never logged done "
                                    "(crashed, or still running)"}


def snapshot():
    return {
        "scheduled_jobs": scheduled_jobs(),
        "omniroute": omniroute_health(),
        "pending_proposals": pending_proposals(),
        "nightly": last_nightly_result(),
    }
