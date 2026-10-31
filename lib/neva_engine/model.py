"""The records the engine passes around."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class ShapeError(Exception):
    """A source is not the shape its collector knows. The message names the file, the field and the fix."""


class Denied(Exception):
    """A source needed a file the deny list refuses. Carries no name: the only safe error is that it happened."""


class ConfigError(Exception):
    """The run cannot start safely. Nothing is written."""


@dataclass
class Fact:
    """A pointer: which line says this, and numbers or dates in `value`. `quote` and `memo` hold text. They live in memory
    for one tick and are never stored."""
    source: str
    kind: str
    subject: str
    value: dict
    path: str = ""
    line: Optional[int] = None
    ts: Optional[str] = None
    quote: str = ""
    memo: dict = field(default_factory=dict)


@dataclass
class SourceRead:
    source: str
    status: str  # ok, proven_empty, absent, failed
    facts: list = field(default_factory=list)
    path: str = ""
    sha256: str = ""
    error: str = ""
    denied: int = 0


@dataclass
class Figure:
    """Where one thing printed on a card comes from.
    line: `value` is on that line. mtime: `value` is the file's change date. file: the path exists.
    sum: the inputs add up to `value`. count: `value` inputs exist. days_since, days_until: `value` days from a date input."""
    display: str
    kind: str
    value: Any = None
    path: str = ""
    line: Optional[int] = None
    inputs: tuple = ()
    iso: str = ""  # a date figure: what `value` means when the line prints it another way


@dataclass
class Card:
    key: str
    rule: str
    kind: str  # failure, money, deadline, decision, build, lead, move
    section: str  # needs_you, opportunities, hero
    severity: float
    title: str
    why: str
    sources: list
    as_of: Optional[str]
    figures: list = field(default_factory=list)
