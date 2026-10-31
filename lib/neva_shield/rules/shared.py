"""Helpers shared by the Shield rule families. Standard library only."""
import math
import re

SECRET_KEY = re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|credential|private[_-]?key|access[_-]?key)")
# Header names that hold a credential whatever the value looks like.
AUTH_HEADERS = frozenset({
    "authorization", "proxy-authorization", "x-api-key", "api-key", "x-goog-api-key",
    "x-auth-token", "private-token",
})
# A field whose name says it holds a date, a path, or a count is not holding a credential,
# even when the word "token" is somewhere in it (claudeCodeFirstTokenDate, tokenPath).
NOT_A_SECRET_KEY = re.compile(r"(?i)(?:date|time$|_at$|expir|count|length|path|dir$|file$|name$|url$|host$|port$|enabled$|type$|version$|scheme$|method$|prefix$|suffix$|format$|[_-]id$|key_?id$|tokens$|^use_)")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")

PLACEHOLDER_WORDS = (
    "example", "placeholder", "changeme", "change-me", "redacted", "your", "yours",
    "xxxx", "dummy", "sample", "replace", "insert", "todo", "notset", "unset",
    "none", "null", "optional", "abcdef", "123456", "test-", "foobar", "<", ">",
)
ENV_REFERENCE = re.compile(r"^\$|^\$\{|\$\{[A-Za-z_]|^%[A-Za-z_]+%$|^op://|^vault:|^keychain:")

LOOPBACK = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1", "host.docker.internal")

# A command position: start of line, or after a pipe, semicolon, &&, ||, $( or a backtick.
COMMAND_POSITION = r"(?:^|[|;&`]|\$\(|&&|\|\|)\s*"

REDACTED = "[REDACTED]"
TRAILING_PUNCTUATION = ".,;:*?!]})"
CREDENTIAL_CHARS = re.compile(r"[A-Za-z0-9_\-./+=~:@!#^*]+")
CONSTANT_NAME = re.compile(r"[A-Z]+(?:_[A-Z0-9]+)+")
CODE_NAME = re.compile(r"[A-Za-z_]{1,32}(?:\.[A-Za-z_]{1,32}){0,8}")
HYPHEN_WORDS = re.compile(r"[a-z_]+(?:[-/.][a-z_]+)+")
UNNAMED_PACKAGE = "<package>"
PACKAGE_NAME = re.compile(r"(@[\w.-]+/)?[\w.-]+(@[\w.+-]+)?")
REFERENCE = re.compile(
    r"(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"%[A-Za-z_][A-Za-z0-9_]*%|(?:op://|vault:|keychain:)[^\s$]+)")
URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'<>)\\]+", re.I)
# Every repeat is bounded, because scrub now reads whole configuration files line by line.
URL_USERINFO = re.compile(r"(?<=://)[^/\s\"'\\]{0,512}@")
BARE_USERINFO = re.compile(r"(?<![\w@.:-])[\w.-]{1,128}:[^\s/@\"':]{1,512}@(?=[A-Za-z][\w-]*\.)")
VALUE = r"[^\s\"'\\)]{1,512}"
AUTH_HEADER = re.compile(
    r"(?i)((?:proxy-)?authorization|x-api-key|x-goog-api-key|api-key|x-auth-token|private-token|cookie)"
    r"([\"']?\s*[:=]\s*[\"']?)((?:[A-Za-z][\w.~+-]*\s+[\"']?)?" + VALUE + ")")
AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic|token|digest)(\s+[\"']?)(" + VALUE + ")")
ASSIGNED = re.compile(r"(?<![\w.-])([\w.-]{1,128})([\"']?\s{0,8}[:=]\s{0,8}[\"']?)([^\s\"'\\)&]{1,512})")
FLAG = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]{0,64})([ \t]{1,8})(" + VALUE + ")")
BASIC_USER = re.compile(r"(?<![\w-])(-u|--user)([ \t]+)([^\s\"'\\):]+:" + VALUE + ")")
HOME_DIRECTORY = re.compile(r"(?<![\w/~-])(?:/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|/root(?=[/\s\"')]|$)|[A-Za-z]:\\Users\\[^\\\s\"']+)")
# Words that follow "token" or "basic" in a sentence. A credential is never one short word.
PROSE_VALUE = re.compile(r"[A-Za-z]?[a-z]{0,13}[.,;:]?")
BEARER_PROSE = frozenset({"token", "tokens", "auth", "authentication", "authorization", "header", "headers", "scheme",
                          "credential", "credentials", "string", "strings", "value", "values"})
EXTRA_SECRET_NAMES = frozenset({"key", "auth", "sig", "signature", "pwd", "pass"})


def is_secret_key(key):
    """True when a field name says it holds a credential and not a date, path, or count."""
    key = str(key)
    return key.lower() in AUTH_HEADERS or (
        bool(SECRET_KEY.search(key)) and not NOT_A_SECRET_KEY.search(key))


def secret_values(key, value):
    """Collect literal credentials, including authentication header components."""
    if not isinstance(value, str) or not is_secret_key(key):
        return []
    if str(key).lower() in AUTH_HEADERS:
        match = re.fullmatch(r"\s*[A-Za-z][A-Za-z0-9._~+-]*\s+(\S+)\s*", value)
        component = match.group(1) if match else value.strip()
        if not component or REFERENCE.fullmatch(component):
            return []
        # Authentication headers explicitly identify credentials. Do not require a
        # provider prefix, entropy threshold, or digit in a Basic encoding.
        return [value, component]
    return [value] if looks_like_secret_value(value) else []


def is_literal_credential(key, value):
    """True when a field should be reported, as opposed to merely kept out of reports.

    Redaction takes any literal under an authentication header. Reporting one as a
    committed secret also needs it to be more than a short word or a documented sample.
    """
    if str(key).lower() in AUTH_HEADERS:
        found = secret_values(key, value)
        return bool(found) and len(found[-1]) >= 8 and not is_placeholder(found[-1])
    return looks_like_secret_value(value)


def entropy(value):
    if not value:
        return 0.0
    counts = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = float(len(value))
    return -sum((n / total) * math.log(n / total, 2) for n in counts.values())


def is_placeholder(value):
    lowered = value.lower()
    if ENV_REFERENCE.search(value):
        return True
    if any(word in lowered for word in PLACEHOLDER_WORDS):
        return True
    if len(set(lowered)) <= 4:
        return True
    return False


def looks_like_secret_value(value):
    """True when a literal is long and mixed enough to be a real credential.

    Deliberately conservative. A value is only a candidate when it is at least 16
    characters of credential charset, mixes letters with digits, is not an environment
    reference or a documented placeholder, and carries at least 3.0 bits of entropy per
    character. Code samples such as os.Getenv("OPENAI_API_KEY") and documentation such as
    "your-api-key-here" are rejected by those gates.
    """
    if not isinstance(value, str):
        return False
    value = value.strip()
    if len(value) < 16 or len(value) > 512:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_\-./+=~:]+", value):
        return False
    if "://" in value or value.startswith("/") or value.startswith("./"):
        return False
    if not (re.search(r"[A-Za-z]", value) and re.search(r"[0-9]", value)):
        return False
    if ISO_DATE.match(value):
        return False
    if is_placeholder(value):
        return False
    return entropy(value) >= 3.0


def walk_json(node, trail=()):
    """Yield (trail, value) for every leaf in a parsed JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_json(value, trail + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_json(value, trail + (str(index),))
    else:
        yield trail, node


def strip_quoted(line):
    """Remove single and double quoted spans so only unquoted shell text is left."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", " ", line)


def fenced_lines(text):
    """Line numbers (1 based) inside a markdown fenced code block.

    A fence closes only on the same character at the same length or longer with no info
    string, so a ```` block can show a ``` block without turning the document inside out.
    """
    fence = None
    marked = set()
    for index, line in enumerate(text.splitlines(), start=1):
        found = re.match(r"\s*(`{3,}|~{3,})(.*)", line)
        if found:
            marks = found.group(1)
            if fence is None:
                fence = marks
                marked.add(index)
                continue
            if marks[0] == fence[0] and len(marks) >= len(fence) and not found.group(2).strip():
                fence = None
                marked.add(index)
                continue
        if fence is not None:
            marked.add(index)
    return marked


def host_of(url):
    found = re.match(r"[a-z][a-z0-9+.-]*://([^/?#\s\"']+)", url, re.I)
    if not found:
        return ""
    authority = found.group(1).split("@")[-1]
    if authority.startswith("["):
        return authority[:authority.find("]") + 1].lower()
    return authority.split(":")[0].lower()


def package_label(spec):
    """Name a package by host when it is a URL, by name when it is plainly one, else not at all.

    Anything else on a launcher line can be a credential in a shape nobody listed, so a report
    prints what it can recognize as safe rather than removing what it recognizes as secret.
    """
    found = URL.search(spec)
    if found:
        return host_of(found.group(0)) or UNNAMED_PACKAGE
    if not PACKAGE_NAME.fullmatch(spec) or any(looks_like_secret_value(part) for part in re.split(r"[/@]", spec)):
        return UNNAMED_PACKAGE
    return spec


def mask_name(name):
    """A configuration key is printed unless it is shaped like a credential itself."""
    return REDACTED if looks_like_secret_value(name) else name


def _is_kept(value):
    """A reference, a placeholder or a piece of code. Credentials do not look like these."""
    value = value.rstrip(TRAILING_PUNCTUATION)
    return (value.startswith((REDACTED, "`")) or "$" in value or is_placeholder(value)
            or CREDENTIAL_CHARS.fullmatch(value) is None or CONSTANT_NAME.fullmatch(value) is not None)


def _is_long_value(value):
    value = value.rstrip(TRAILING_PUNCTUATION)
    return len(value) >= 16 and HYPHEN_WORDS.fullmatch(value) is None


def _is_plain_word(value):
    """`auth: required` and `--key=2` are prose and sort flags, not credentials."""
    value = value.rstrip(TRAILING_PUNCTUATION)
    return value.isdigit() or PROSE_VALUE.fullmatch(value) is not None or CODE_NAME.fullmatch(value) is not None


def _userinfo(found):
    """`git@` and the `user:pass@` of a documented connection string are not credentials."""
    user, colon, secret = found.group(0)[:-1].rpartition(":")
    if not colon:  # A lone name is an account, as in plugin://name@owner, unless it is a token.
        return REDACTED + "@" if looks_like_secret_value(secret) else found.group(0)
    return found.group(0) if not secret or _is_kept(secret) or _is_plain_word(secret) else REDACTED + "@"


def _header(found):
    last = found.group(3).split()[-1].lstrip("\"'")
    kept = _is_kept(last) or last.rstrip(".,;:").lower() in BEARER_PROSE
    return found.group(1) + found.group(2) + (found.group(3) if kept else REDACTED)


def _scheme(found):
    name, gap, value = found.group(1), found.group(2), found.group(3)
    if _is_kept(value):
        return found.group(0)
    if name.lower() == "bearer":
        prose = value.rstrip(TRAILING_PUNCTUATION).lower() in BEARER_PROSE
    else:
        prose = not _is_long_value(value)
    return found.group(0) if prose else name + gap + REDACTED


def _is_assignment_name(name, value):
    name = name.lstrip("-").lower()
    if name in AUTH_HEADERS:  # Already handled with its scheme by AUTH_HEADER.
        return False
    if name in EXTRA_SECRET_NAMES:  # Common words: `key: neva.profile` is not a credential.
        return _is_long_value(value)
    return is_secret_key(name)


def _scrub_assignments(text):
    """Redact name=value and name: value pairs.

    The search resumes right after a non-secret name, not after its value, because the
    value of https: is a whole URL that can hold a token= of its own.
    """
    out = []
    position = 0
    while True:
        found = ASSIGNED.search(text, position)
        if not found:
            return "".join(out) + text[position:]
        if _is_assignment_name(found.group(1), found.group(3)):
            out.append(text[position:found.start(3)])
            value = found.group(3)
            out.append(value if _is_kept(value) or _is_plain_word(value) else REDACTED)
            position = found.end()
        else:
            out.append(text[position:found.start(3)])
            position = found.start(3)


def _flag(found):
    value = found.group(3)
    if value.startswith("-") or not is_secret_key(found.group(1).lstrip("-")):
        return found.group(0)
    return found.group(1) + found.group(2) + (value if _is_kept(value) or _is_plain_word(value) else REDACTED)


def _basic_user(found):
    password = found.group(3).partition(":")[2]
    if _is_kept(password):
        return found.group(0)
    return found.group(1) + found.group(2) + REDACTED


def scrub_credentials(text):
    """Remove credentials by their shape, wherever the text came from."""
    text = URL_USERINFO.sub(_userinfo, text)
    text = BARE_USERINFO.sub(REDACTED + "@", text)
    text = AUTH_HEADER.sub(_header, text)
    text = AUTH_SCHEME.sub(_scheme, text)
    text = _scrub_assignments(text)
    text = BASIC_USER.sub(_basic_user, text)
    return FLAG.sub(_flag, text)


def has_credential(text):
    """True when text holds a literal credential in a known shape, in any field."""
    return scrub_credentials(text) != text


def scrub(text):
    """The last pass before anything is reported: credentials, then home directories."""
    return HOME_DIRECTORY.sub("~", scrub_credentials(text))


def is_loopback(url):
    host = host_of(url)
    return host in LOOPBACK or host.endswith(".localhost")
