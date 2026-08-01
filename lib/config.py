"""Shared config reader for python tools. Mirror of config.sh, same file, same rules.

Usage:
    from lib.config import load
    cfg = load()          # dict; raises SystemExit with the exact fix on any problem
"""
import os
import re
import stat
import sys

CONFIG_PATH = os.environ.get(
    "NEVA_CONFIG", os.path.expanduser("~/.config/neva/identity.env"))
LINE = re.compile(r'^([A-Z_]+)="([^"]*)"\s*$')
# OWNER_CHAT_ID is deliberately NOT required: it is empty until Telegram setup, and a
# placeholder string there would satisfy every non-empty check while sending to nowhere.
# Tools that actually send must call can_send() instead of assuming it is populated.
REQUIRED = ("OWNER_NAME", "AGENT_NAME", "TIMEZONE", "VAULT_PATH", "WORKSPACE_PATH")


def _die(msg, fix):
    sys.stderr.write(f"{msg}\nfix: {fix}\n")
    raise SystemExit(78)  # EX_CONFIG


def load():
    if not os.path.isfile(CONFIG_PATH):
        _die(f"config missing: {CONFIG_PATH}",
             "run install.sh (it interviews you and writes this file)")

    mode = stat.S_IMODE(os.stat(CONFIG_PATH).st_mode)
    if mode not in (0o600, 0o400):
        _die(f"config perms are {oct(mode)[2:]}, must be 600",
             f"chmod 600 '{CONFIG_PATH}'")

    cfg = {}
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            m = LINE.match(line)
            if not m:
                _die(f"config line {n} invalid (only KEY=\"value\" allowed): {line[:60]}",
                     "edit the file or re-run install.sh")
            cfg[m.group(1)] = m.group(2)

    for key in REQUIRED:
        if not cfg.get(key):
            _die(f"config key {key} is empty in {CONFIG_PATH}",
                 "edit the file or re-run install.sh")

    home = os.path.expanduser("~")
    for key in ("VAULT_PATH", "WORKSPACE_PATH", "LEDGER_FILE", "FOOD_DIR"):
        if key in cfg and cfg[key].startswith("$HOME"):
            cfg[key] = cfg[key].replace("$HOME", home, 1)
    return cfg


def can_send(cfg):
    """True only when a real chat id exists. Never post to an unset/placeholder id."""
    return bool(cfg.get("OWNER_CHAT_ID"))
