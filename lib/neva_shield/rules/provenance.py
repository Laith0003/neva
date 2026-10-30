"""Provenance rules: where plugin code comes from, and who can read the credentials."""
import re

from . import shared

KINDS = ("settings", "marketplace", "credentials", "hooks_config", "mcp")

# Keys that name where plugin code is installed from. Inside an explicit marketplace block
# a url or repo is the install source; everywhere else only "source" is, because a
# package manifest's repository and homepage are metadata, not an install channel.
MARKETPLACE_KEYS = frozenset({"source", "url", "repo", "repository", "marketplace", "git", "uri"})
SOURCE_KEYS = frozenset({"source", "marketplace"})
# Contact and documentation links are not where plugin code comes from.
NOT_A_SOURCE = frozenset({"author", "maintainer", "maintainers", "homepage", "docs", "documentation",
                          "bugs", "issues", "funding", "support", "contact", "owner", "metadata", "license"})
PINNED_REF = re.compile(r"(?:@|#|/tree/|/commit/|[?&]ref=)(?:v?\d+(?:\.\d+)*|[0-9a-f]{7,40})/?$")
PLAIN_HTTP = re.compile(r"^http://", re.I)
UNSAFE_SCHEME = re.compile(r"^(?:git|ftp|file)://", re.I)
GITHUB_SHORTHAND = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*)/[A-Za-z0-9][A-Za-z0-9._-]*$")


def _marketplace_sources(data):
    """Yield (label, value) for every plugin or marketplace source in a settings document."""
    if not isinstance(data, dict):
        return
    for key in ("extraKnownMarketplaces", "knownMarketplaces", "marketplaces"):
        block = data.get(key)
        if isinstance(block, dict):
            for name, entry in block.items():
                for trail, value in shared.walk_json(entry):
                    if isinstance(value, str) and (not trail or trail[-1] in MARKETPLACE_KEYS):
                        yield key + "." + str(name), value
        elif isinstance(block, list):
            for index, entry in enumerate(block):
                for trail, value in shared.walk_json(entry):
                    if isinstance(value, str) and (not trail or trail[-1] in MARKETPLACE_KEYS):
                        yield key + "[" + str(index) + "]", value
    for trail, value in shared.walk_json(data):
        if isinstance(value, str) and trail and trail[-1] in SOURCE_KEYS and "marketplace" in " ".join(trail).lower():
            yield ".".join(trail), value


def check(source, add):
    data = source.data()
    if data is not None:
        pairs = list(_marketplace_sources(data))
        if source.has("marketplace"):
            pairs.extend((".".join(trail), value) for trail, value in shared.walk_json(data)
                         if isinstance(value, str) and trail and trail[-1] in SOURCE_KEYS)
        for label, value in pairs:
            if NOT_A_SOURCE.intersection(part.lower() for part in label.split(".")):
                continue
            _check_source(source, add, label, value)

    if source.has("credentials") and source.mode & 0o077:
        add("PROV002", "high", 1,
            "Credential file is readable by group or other users (mode " + oct(source.mode & 0o777) + ").",
            "Run chmod 600 on this file.")
    if source.has("settings", "hooks_config", "marketplace") and source.mode & 0o002:
        add("PROV003", "medium", 1,
            "Configuration file is world writable (mode " + oct(source.mode & 0o777) + "), so any local process can add permissions or hooks to it.",
            "Run chmod go-w on this file.")


def _check_source(source, add, label, value):
    value = value.strip()
    if not value:
        return
    line = source.find_line(value, label.split(".")[-1])
    printer = source.printer
    label = ".".join(printer.name(shared.mask_name(part), "source") for part in label.split("."))
    if UNSAFE_SCHEME.match(value):
        add("PROV001", "high", line,
            "Plugin source " + label + " uses the unauthenticated scheme " + value.split("://")[0] + "://, so its contents can be substituted in transit.",
            "Change " + label + " to an https URL.")
    elif PLAIN_HTTP.match(value):
        add("PROV001", "high", line,
            "Plugin source " + label + " is served over plaintext http from " + printer.host(shared.host_of(value)) + ", so the plugin code can be substituted in transit.",
            "Change " + label + " to the https URL for the same host.")
    elif value.lower().startswith("https://") or GITHUB_SHORTHAND.match(value):
        if not PINNED_REF.search(value):
            add("PROV004", "medium", line,
                "Plugin source " + label + " is not pinned, so it installs whatever that branch holds at install time.",
                "Append a tag or commit to " + label + ", for example " + printer.package(shared.package_label(value)) + "@v1.2.3.")
