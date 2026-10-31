"""The two gates in front of every output.

Deny: a path is refused before it is opened, and a term anywhere in a card drops the whole card. Whole word, case and
compatibility forms folded, dotted forms caught, never a substring: a list entry of five letters must not fire inside
ordinary words. Number: a figure on a card must come from a source line that still says it, re-read at output time.
Any digit no figure accounts for drops the card. Drops are counted; the text is never logged."""
from __future__ import annotations

import datetime
import fnmatch
import json
import os
import re
import unicodedata

from .model import ConfigError

ARABIC = re.compile(r"[\u0600-\u06FF]")
ARABIC_PREFIX = "(?:\u0648\u0627\u0644|\u0628\u0627\u0644|\u0627\u0644|\u0644\u0644|[\u0648\u0628\u0644\u0641\u0643])?"  # wal, bal, al, lil, and one letter: w b l f k
NUMBER = re.compile(r"(?<![^\W_])\d[\d,]*(?:\.\d+)?")  # W27 is a name, not a figure; the scan must not restart inside it


def fold(text):
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if unicodedata.category(c) != "Mn" and c != "ـ")
    return unicodedata.normalize("NFKC", text).casefold()


def plain(text):
    """A line as words: table pipes and emphasis marks are layout, not what it says."""
    return " ".join(re.sub(r"[|*`]", " ", text).split())


def views(text):
    """The two ways a line is read. Folded keeps A.R.E.S whole. Spaced turns symbols, punctuation and modifier letters into
    spaces first, or a trademark sign folds into letters and the word before it hides."""
    spaced = "".join(" " if unicodedata.category(c)[0] in "SP" or unicodedata.category(c) == "Lm" else c for c in text)
    return fold(text), fold(spaced)


def term_pattern(term):
    words = [w for w in fold(term).split() if w]
    if len(words) == 1:
        body = r"(?:[^\w\s]|_)*".join(re.escape(c) for c in words[0])
    else:
        body = r"[\W_]*".join(re.escape(w) for w in words)
    prefix = ARABIC_PREFIX if ARABIC.search(body) else ""
    return r"(?<![^\W\d_])" + prefix + "(?:" + body + r")(?![^\W\d_])"


def strings(value):
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


class Deny:
    def __init__(self, terms=(), paths=(), tags=()):
        self.paths = [p.casefold() for p in paths]
        self.tags = {fold(t) for t in tags}
        self.regex = re.compile("|".join(term_pattern(t) for t in terms)) if terms else None

    @classmethod
    def load(cls, path):
        """None is a user with no list, said out loud. Anything else must be a real list: an empty or mistyped file would
        otherwise fail open and show everything it was written to hide."""
        if path is None:
            return cls()
        if not isinstance(path, str) or not path.strip():
            raise ConfigError("deny_file: not a path. Give the file, or null for no list; nothing was written.")
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise ConfigError(f"deny_file {path}: cannot read it ({e}). Restore the file; nothing was written.")
        terms = data.get("terms") if isinstance(data, dict) else None
        if not terms or not strings(terms):
            raise ConfigError(f"deny_file {path}: `terms` must be a non-empty list of strings. Fix the file; nothing was written.")
        for key in ("paths", "tags"):
            if not strings(data.get(key, [])):
                raise ConfigError(f"deny_file {path}: `{key}` must be a list of strings. Fix the file; nothing was written.")
        return cls(terms, data.get("paths", ()), data.get("tags", ()))

    def path_denied(self, rel):
        rel = rel.casefold()
        return any(fnmatch.fnmatchcase(rel, p) for p in self.paths)

    def tagged(self, tags):
        """A nested tag counts at every level: a/b/c is a, b, c, a/b and a/b/c."""
        names = set()
        for tag in tags:
            parts = [p for p in fold(tag).split("/") if p]
            names.update(parts)
            names.update("/".join(parts[:i + 1]) for i in range(len(parts)))
        return bool(self.tags & names)

    def hit(self, text):
        return bool(self.regex) and any(self.regex.search(v) for v in views(text))


class Gate:
    def __init__(self, may_read, today):
        self.may_read = may_read
        self.today = today
        self.lines = {}

    def line_of(self, path, line):
        if path not in self.lines:
            with open(path, encoding="utf-8") as f:
                self.lines[path] = f.read().split("\n")
        rows = self.lines[path]
        return rows[line - 1] if line and 0 < line <= len(rows) else None

    def verified(self, fig):
        try:
            return self._verified(fig)
        except (OSError, ValueError, TypeError):
            return False

    def _verified(self, fig):
        if fig.kind == "line":
            if not self.may_read(fig.path):
                return False
            text = self.line_of(fig.path, fig.line)
            if text is None:
                return False
            if isinstance(fig.value, (int, float)):
                return str(fig.value) in {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text)}
            return plain(str(fig.value)) in plain(text)
        if fig.kind == "mtime":
            return self.may_read(fig.path) and \
                datetime.date.fromtimestamp(os.stat(fig.path).st_mtime).isoformat() == fig.value
        if fig.kind == "job_day":
            with open(fig.path, encoding="utf-8") as f:
                finished = json.load(f).get("finished")
            return datetime.date.fromtimestamp(finished).isoformat() == fig.value
        if fig.kind == "file":
            return self.may_read(fig.path) and os.path.exists(fig.path)
        if not all(self.verified(i) for i in fig.inputs):
            return False
        if fig.kind == "sum":
            return sum(i.value for i in fig.inputs) == fig.value
        if fig.kind == "count":
            return len(fig.inputs) == fig.value
        if fig.kind in ("days_since", "days_until"):
            d = datetime.date.fromisoformat(fig.inputs[0].iso)
            span = (self.today - d).days if fig.kind == "days_since" else (d - self.today).days
            return span == fig.value
        return False

    def number_ok(self, card):
        if not all(self.verified(f) for f in card.figures):
            return False
        text = f"{card.title}\n{card.why}"
        for fig in sorted(card.figures, key=lambda f: -len(f.display)):
            if fig.display:
                text = re.sub(r"(?<!\d)(?<!\d,)" + re.escape(fig.display) + r"(?!\d|,\d)", " ", text)
        return not NUMBER.search(text)
