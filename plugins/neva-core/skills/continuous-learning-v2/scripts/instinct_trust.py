"""instinct_trust: the one parser, hash and approval check for instinct notes (continuous-learning-v2, Neva).

A lesson reaches a session only with an engine record of approval:
  - a global note an apply created from a ticked promotion: a row in promoted-notes.json marked
    approved, whose hash still matches the note, or
  - a note `add` wrote or `add --restate` vouched for: a row in user-stated.json whose hash still
    matches the note.
Everything else, the nightly analyzer's own notes included, is a candidate and is not injected.

instinct-cli.py imports this module; the hooks (neva_hooks/common.py) load it by path. Both use
the same parse_instinct_file and note_hash, so a note cannot pass one and fail the other.

Stdlib only. Read-only: nothing here writes a file.
"""
import functools
import hashlib
import json
import os
import re
from pathlib import Path

INT_FIELDS = {"evidence_count", "decay_weeks_applied"}
TRUST_FIELDS = ("trigger", "domain", "scope", "source")
USER_STATED_NAME = "user-stated.json"
PROMOTED_NOTES_NAME = "promoted-notes.json"
GLOBAL_PREFIX = "vault:06 Memory/instincts/global/"
# The state files are a few KB; anything far larger is not read, and nothing injects.
MAX_STATE_BYTES = 8 * 1024 * 1024


def parse_instinct_file(content: str) -> list:
    """Parse instinct markdown (or multi-block import files).

    Each instinct is delimited by a pair of ``---`` markers. Instinct bodies
    must use ``***`` or ``___`` for horizontal rules.
    """
    instincts = []
    current = {}
    in_frontmatter = False
    content_lines = []
    for line in content.split('\n'):
        if line.strip() == '---':
            if in_frontmatter:
                in_frontmatter = False
            else:
                in_frontmatter = True
                if current:
                    current['content'] = '\n'.join(content_lines).strip()
                    instincts.append(current)
                current = {}
                content_lines = []
        elif in_frontmatter:
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                    value = value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
                elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
                    value = value[1:-1].replace("''", "'")
                if key == 'confidence':
                    try:
                        current[key] = float(value)
                    except ValueError:
                        current[key] = 0.5
                elif key in INT_FIELDS:
                    try:
                        current[key] = int(value)
                    except ValueError:
                        current[key] = 0
                else:
                    current[key] = value
        else:
            content_lines.append(line)
    if current:
        current['content'] = '\n'.join(content_lines).strip()
        instincts.append(current)
    return [i for i in instincts if i.get('id')]


def note_hash(inst: dict, scoped: bool = True) -> str:
    """The whole note as trust sees it: the fields that matter for trust (TRUST_FIELDS) and the full
    body, whitespace-collapsed. An edit anywhere in the body, or to one of those fields, changes it.
    scoped=False leaves out scope and source, which a promotion changes on purpose, to compare a
    promoted note with the notes it came from."""
    keys = TRUST_FIELDS if scoped else ("trigger", "domain")
    parts = [f"{k}={inst.get(k, '')}" for k in keys] + [str(inst.get('content', ''))]
    return hashlib.sha256(" ".join("\n".join(parts).split()).encode("utf-8")).hexdigest()


def action_text(inst: dict) -> str:
    """The first paragraph under `## Action`, or '' when the note has none."""
    m = re.search(r'## Action\s*\n\s*(.+?)(?:\n\n|\n##|$)', str(inst.get('content', '')), re.DOTALL)
    return m.group(1).strip() if m else ''


@functools.lru_cache(maxsize=256)
def _real_dir(directory: str) -> str:
    return os.path.realpath(directory)


def _realpath(path: str) -> str:
    """os.path.realpath, with each folder resolved once per process: the hooks resolve thousands of
    notes in a few folders. A leaf that is itself a symlink is resolved in full."""
    head, tail = os.path.split(os.path.abspath(path))
    if not tail or os.path.islink(path):
        return os.path.realpath(path)
    return os.path.join(_real_dir(head), tail)


def vault_ref(path, vault):
    """`vault:<relative path>` for a path inside the vault, else None. Both sides are resolved, so a
    symlinked vault path and its real path give the same reference."""
    if not vault or not path:
        return None
    try:
        v = _real_dir(os.path.expanduser(os.fspath(vault))).rstrip(os.sep) or os.sep
        p = _realpath(os.fspath(path))
    except (OSError, ValueError, TypeError):
        return None
    if p == v:
        return "vault:."
    prefix = v if v.endswith(os.sep) else v + os.sep
    if not p.startswith(prefix):
        return None
    return "vault:" + p[len(prefix):].replace(os.sep, "/")


def _abs(environ, name):
    value = environ.get(name)
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else None


def state_dir(environ=None):
    """The instinct state folder, resolved exactly as instinct-cli.py resolves it:
    NEVA_INSTINCT_STATE_DIR, else NEVA_STATE_DIR/instincts, else $XDG_STATE_HOME/neva/instincts,
    else ~/.local/state/neva/instincts. A relative value is ignored, as the CLI ignores it."""
    env = os.environ if environ is None else environ
    override = _abs(env, "NEVA_INSTINCT_STATE_DIR")
    if override:
        return override
    root = _abs(env, "NEVA_STATE_DIR")
    if root:
        return root / "instincts"
    xdg = _abs(env, "XDG_STATE_HOME")
    return ((xdg / "neva") if xdg else Path.home() / ".local" / "state" / "neva") / "instincts"


def _read_rows(path: Path) -> dict:
    """One state file as {ref: row}. Missing, too large, unreadable or not a JSON object: {}."""
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            return {}
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_records(directory=None):
    """(user-stated rows, promoted-note rows) from the instinct state folder, read-only."""
    d = Path(directory) if directory else state_dir()
    return _read_rows(d / USER_STATED_NAME), _read_rows(d / PROMOTED_NOTES_NAME)


def stated_now(stated: dict, ref, inst: dict) -> bool:
    """True while the note still teaches exactly what `add` recorded for it."""
    row = stated.get(ref) if ref else None
    return isinstance(row, dict) and bool(row.get('sha')) and row['sha'] == note_hash(inst)


def approved_now(promoted: dict, ref, inst: dict) -> bool:
    """True for a global note an apply created after the human ticked it, while it still says the same."""
    row = promoted.get(ref) if ref else None
    return isinstance(row, dict) and bool(row.get('approved')) and bool(row.get('sha')) \
        and row['sha'] == note_hash(inst)


def has_record(ref, stated: dict, promoted: dict) -> bool:
    """Cheap pre-check before any file is read or hashed: is there a row for this note at all."""
    return bool(ref) and (ref in stated or (ref.startswith(GLOBAL_PREFIX) and ref in promoted))


def approved_note(text: str, ref, stated: dict, promoted: dict):
    """The parsed note when it carries an engine record of approval and still matches it, else None.

    A promoted row vouches only for a note in the global folder; a user-stated row for any note.
    The caller must build what it shows from the returned note, never from another parse of the
    file: this parse is the one the hash covers."""
    if not has_record(ref, stated, promoted):
        return None
    parsed = parse_instinct_file(text)
    if not parsed:
        return None
    inst = parsed[0]
    if stated_now(stated, ref, inst):
        return inst
    if ref.startswith(GLOBAL_PREFIX) and approved_now(promoted, ref, inst):
        return inst
    return None
