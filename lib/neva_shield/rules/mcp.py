"""MCP rules: an MCP server is code the agent launches and a channel it trusts."""
import re

from . import shared

KINDS = ("mcp",)

LAUNCHERS = frozenset({"npx", "bunx", "pnpx", "uvx", "pipx", "uv", "npm", "pnpm", "yarn", "bun"})
PINNED = re.compile(r"(?:@|==)v?\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?$")
GIT_PINNED = re.compile(r"(?:@|#)[0-9a-f]{40}$")


def _pinned(spec):
    if "://" in spec or spec.startswith("git+"):
        return bool(GIT_PINNED.search(spec))
    return bool(PINNED.search(spec))


AUTH_KEY = re.compile(r"(?i)authorization|bearer|api[_-]?key|token|secret|credential|x-api")


def _servers(source):
    """Yield (name, config dict) for every MCP server declared in this file."""
    data = source.toml() if source.path.suffix.lower() == ".toml" else source.data()
    if isinstance(data, dict):
        for key in ("mcpServers", "mcp_servers", "mcp", "servers", "context_servers"):
            block = data.get(key)
            if key == "mcp" and isinstance(block, dict):
                block = block.get("servers", block)
            if isinstance(block, dict):
                for name, config in block.items():
                    if isinstance(config, dict):
                        yield str(name), config
        projects = data.get("projects")
        if isinstance(projects, dict):
            for project in projects.values():
                if isinstance(project, dict) and isinstance(project.get("mcpServers"), dict):
                    for name, config in project["mcpServers"].items():
                        if isinstance(config, dict):
                            yield str(name), config


def _package_specs(config):
    """Return every explicit install package, or the implicit launcher package.

    Explicit package options select the installed code; the following positional
    operand is then a command to execute, not another package to install.
    """
    command = str(config.get("command") or "").strip()
    args = [str(item) for item in config.get("args") or [] if isinstance(item, (str, int))]
    words = command.split()
    if not words:
        return []
    binary = words[0].rsplit("/", 1)[-1].lower()
    if binary not in LAUNCHERS:
        return []
    package_options = {"--package", "-p"} if binary in {"npx", "npm", "pnpm", "pnpx", "bun", "bunx"} else set()
    if binary in {"uv", "uvx"}:
        package_options = {"--from", "--with", "-w"}
    elif binary == "pipx":
        package_options = {"--spec"}
    # These option values configure the launcher and are not install operands.
    value_options = {"--registry", "--cache", "--userconfig", "--prefix", "--cwd", "--directory",
                     "--index-url", "--extra-index-url", "--python", "--python-version", "--index"}
    candidates = words[1:] + args
    packages = []
    selects_package = False
    positional = None
    index = 0
    while index < len(candidates):
        item = candidates[index]
        option, equals, value = item.partition("=")
        if option in package_options:
            if option not in {"--with", "-w"}:
                selects_package = True
            if equals:
                packages.append(value)
            elif index + 1 < len(candidates):
                index += 1
                packages.append(candidates[index])
            else:
                packages.append("")
        elif item == "--":
            if positional is None and index + 1 < len(candidates):
                positional = candidates[index + 1]
            break
        elif option in value_options and not equals:
            index += 1
        elif not item.startswith("-") and item not in {"run", "exec", "dlx", "install", "tool"} and positional is None:
            positional = item
            # npm exec continues parsing options until an explicit --. Other
            # launchers hand arguments after the executable to that program.
            if binary != "npm":
                break
        index += 1
    if not selects_package and positional is not None:
        packages.append(positional)
    return packages


def _urls(config):
    for key in ("url", "endpoint", "serverUrl", "httpUrl", "sse_url"):
        value = config.get(key)
        if isinstance(value, str) and "://" in value:
            yield value


def _pin_fix(package, is_url):
    if is_url:
        return "Pin " + package + " to an immutable tag or commit, and bump it deliberately."
    return "Pin it to an exact version, for example " + package + "@1.2.3, and bump it deliberately."


def _has_auth(config):
    for trail, value in shared.walk_json(config):
        if trail and AUTH_KEY.search(trail[-1]) and isinstance(value, str) and value.strip():
            return True
        if isinstance(value, str) and value.lower().startswith("bearer "):
            return True
    return False


def check(source, add):
    for name, config in _servers(source):
        line = source.find_line('"' + name + '"', name)
        printer = source.printer
        shown = printer.name(shared.mask_name(name), "server")

        for spec in _package_specs(config):
            label = shared.package_label(spec)
            is_url = label != spec
            shown_package = printer.package(label)
            if spec.endswith("@latest") or spec.endswith("@next") or spec.endswith("@beta"):
                add("MCP001", "medium", source.find_line(spec, '"' + name + '"'),
                    "MCP server " + shown + " launches " + shown_package + ", so it installs whatever is published at the moment it starts.",
                    _pin_fix(shown_package if is_url else printer.package(spec.rsplit("@", 1)[0]), is_url))
            elif not _pinned(spec):
                add("MCP001", "medium", source.find_line(spec, '"' + name + '"'),
                    "MCP server " + shown + " launches " + shown_package + " without an exact version, so it installs whatever is published at the moment it starts.",
                    _pin_fix(shown_package if is_url else printer.package(spec.split("@")[0]), is_url))

        for url in _urls(config):
            if url.lower().startswith("http://") and not shared.is_loopback(url):
                add("MCP002", "high", source.find_line(url, '"' + name + '"'),
                    "MCP server " + shown + " is reached over plaintext http at " + printer.host(shared.host_of(url)) + ", so its traffic and any token it carries are readable in transit.",
                    "Change the url for " + shown + " to https, and send its credential in an Authorization header from an environment variable.")
            elif not shared.is_loopback(url) and not _has_auth(config):
                add("MCP004", "medium", source.find_line(url, '"' + name + '"'),
                    "Remote MCP server " + shown + " at " + printer.host(shared.host_of(url)) + " is configured with no authentication.",
                    'Add a headers block to ' + shown + ' with "Authorization": "Bearer ${MCP_TOKEN}" and set MCP_TOKEN in your environment.')

        env = config.get("env") if isinstance(config.get("env"), dict) else {}
        for key, value in env.items():
            if not isinstance(value, str):
                continue
            if shared.looks_like_secret_value(value):
                field = printer.name(shared.mask_name(str(key)), "field")
                add("MCP003", "high", source.find_line('"' + str(key) + '"', '"' + name + '"'),
                    "MCP server " + shown + " carries an inline credential in env." + field + ". The value is not reproduced here.",
                    "Replace the literal with ${" + field + "}, export " + field + " from your shell or secret manager, and rotate the value that was committed.")
