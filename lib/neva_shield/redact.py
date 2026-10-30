"""Redaction shared by all finding families and report metadata."""
from .rules.secrets import PROVIDERS, ASSIGNMENT
from .rules import shared


def redact(text, values=()):
    for value in sorted(set(values), key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    for pattern, _ in PROVIDERS:
        text = pattern.sub("[REDACTED]", text)
    return shared.scrub(text)


def credential_values(source):
    values = []
    data = source.toml() if source.path.suffix.lower() == ".toml" else source.data()
    if data is not None:
        for trail, value in shared.walk_json(data):
            if trail:
                values.extend(shared.secret_values(trail[-1], value))
    else:
        for found in ASSIGNMENT.finditer(source.text):
            if shared.is_secret_key(found.group("key")) and shared.looks_like_secret_value(found.group("value")):
                values.append(found.group("value"))
    return values
