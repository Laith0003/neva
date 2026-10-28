"""Push a compiled brain pack to the omni worker.

Standard library only, and the opener is injectable so the tests never open a socket. Every
failure raises with the status, the host, and the two values that have to match: a push that
quietly does nothing is worse than one that stops and says why.
"""
import hashlib, datetime, json, os, re, urllib.error, urllib.parse, urllib.request

from .safe_write import atomic_write

ENDPOINT = "/brainpack"
TIMEOUT = 30
CONVERSATIONS_DIR = ("06 Memory", "Conversations")


def _validated_url(url, base=True):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
        valid = (parsed.scheme == "https" and parsed.hostname and
                 parsed.username is None and parsed.password is None and
                 not parsed.query and not parsed.fragment and
                 not any(character.isspace() or ord(character) < 32 for character in url))
        if base:
            valid = valid and parsed.path in ("", "/")
        if not valid:
            raise ValueError("invalid address")
    except (ValueError, TypeError, AttributeError):
        raise ValueError("omni url: use an HTTPS host without credentials, path, query or fragment") from None
    return parsed, (parsed.hostname.lower(), port if port is not None else 443)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        try:
            _, origin = _validated_url(request.full_url, base=False)
            _, destination = _validated_url(newurl, base=False)
            if origin != destination:
                raise ValueError("different origin")
        except ValueError:
            raise urllib.error.URLError("omni redirect refused: require HTTPS on the original origin") from None
        return super().redirect_request(request, response, code, message, headers, newurl)


def build_request(url, token, pack):
    _validated_url(url)
    target = url.rstrip("/") + ENDPOINT
    body = json.dumps(pack, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(
        target,
        data=body,
        method="PUT",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def load_pack(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"no brain pack at {path}: run neva brainpack to compile one, or pass --pack with its path"
        ) from None
    except json.JSONDecodeError as e:
        raise ValueError(f"the brain pack at {path} is not JSON ({e}): recompile it with neva brainpack") from None


def push_pack(url, token, pack, opener=None, timeout=TIMEOUT):
    if not url:
        raise ValueError("omni url is empty: pass --url or set NEVA_OMNI_URL to your worker's https address")
    if not token:
        raise ValueError(
            "omni token is empty: set NEVA_OMNI_TOKEN to the same value you gave "
            "wrangler secret put DEVICE_TOKEN"
        )
    if not isinstance(pack, dict) or not isinstance(pack.get("tiers"), dict) or not pack["tiers"]:
        raise ValueError("the brain pack has no tiers: run neva brainpack to compile one before pushing")

    _validated_url(url)
    host = urllib.parse.urlsplit(url).netloc or url
    opener = opener or urllib.request.build_opener(SafeRedirectHandler())

    # Source paths are local provenance for the owner, not worker context.
    remote_pack = {key: value for key, value in pack.items() if key != "sources"}
    try:
        with opener.open(build_request(url, token, remote_pack), timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else ""
        hint = (
            " check NEVA_OMNI_TOKEN matches the worker's DEVICE_TOKEN secret"
            if e.code in (401, 403)
            else ""
        )
        raise RuntimeError(f"omni at {host} refused the push with {e.code}: {detail}.{hint}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"omni at {host} is unreachable: {e.reason}") from None

    text = raw.decode("utf-8", "replace")
    try:
        reply = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"omni at {host} replied with something that is not JSON: {text[:200]}") from None
    _check_acknowledgement(host, pack, reply)
    return reply


def _check_acknowledgement(host, pack, reply):
    # Parsed JSON is not a confirmation. Only stored:true with the exact tier sizes that were
    # sent proves the worker holds this pack; anything else may mean the old pack is still live.
    fix = "check the worker logs and the deployed version, then push again"
    if not isinstance(reply, dict):
        raise RuntimeError(f"omni at {host} did not confirm the push: expected a JSON object, "
                           f"got {type(reply).__name__}; {fix}")
    if reply.get("stored") is not True:
        raise RuntimeError(f"omni at {host} did not confirm the push: field stored is "
                           f"{json.dumps(reply.get('stored'))}, expected true; {fix}")
    sent = {name: tier.get("chars") if isinstance(tier, dict) else None
            for name, tier in pack["tiers"].items()}
    if reply.get("tiers") != sent:
        raise RuntimeError(f"omni at {host} did not confirm the push: field tiers is "
                           f"{json.dumps(reply.get('tiers'))}, expected {json.dumps(sent, sort_keys=True)}; {fix}")


def _get_json(url, token, path, opener, timeout):
    _validated_url(url)
    target = url.rstrip("/") + path
    request = urllib.request.Request(target, method="GET", headers={"Authorization": f"Bearer {token}"})
    opener = opener or urllib.request.build_opener(SafeRedirectHandler())
    host = urllib.parse.urlsplit(url).netloc or url

    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else ""
        hint = (
            " check NEVA_OMNI_TOKEN matches the worker's DEVICE_TOKEN secret"
            if e.code in (401, 403)
            else ""
        )
        raise RuntimeError(f"omni at {host} refused {path} with {e.code}: {detail}.{hint}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"omni at {host} is unreachable: {e.reason}") from None

    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"omni at {host} replied with something that is not JSON: {text[:200]}") from None


def _sanitize_title(title):
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', " ", title or "").strip()
    return cleaned or "untitled"


def _thread_date(thread):
    updated_at = thread.get("updated_at") or 0
    return datetime.datetime.fromtimestamp(updated_at / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")


def _owner_marker(thread):
    return "neva_omni_thread: " + hashlib.sha256(thread["id"].encode("utf-8")).hexdigest()


def _thread_path(vault, thread):
    name = "neva-thread-" + hashlib.sha256(thread["id"].encode("utf-8")).hexdigest() + ".md"
    return os.path.join(vault, *CONVERSATIONS_DIR, name)


def _check_ownership(path, thread):
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    directory = os.open(os.path.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in os.path.dirname(path).split(os.path.sep)[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(os.path.basename(path), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            prefix = stream.read(256)
        if not prefix.startswith("---\n" + _owner_marker(thread) + "\n"):
            raise ValueError("ownership missing at {}: move the unrelated note before syncing".format(path))
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ValueError("symlink or unsafe note at {}: restore a regular path".format(path)) from error
    finally:
        os.close(directory)


def thread_markdown(thread):
    lines = ["---", _owner_marker(thread), "tags: [content, conversation]", "---", "", f"# {thread.get('title') or thread.get('id', '')}", ""]
    for message in thread.get("messages", []):
        model = message.get("model")
        lines.append(f"### {message['role']} ({model})" if model else f"### {message['role']}")
        lines.append("")
        lines.append(message.get("content", ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def sync_threads(url, token, vault, opener=None, timeout=TIMEOUT):
    if not url:
        raise ValueError("omni url is empty: pass --url or set NEVA_OMNI_URL to your worker's https address")
    if not token:
        raise ValueError(
            "omni token is empty: set NEVA_OMNI_TOKEN to the same value you gave "
            "wrangler secret put DEVICE_TOKEN"
        )
    if not vault:
        raise ValueError("vault is empty: pass --vault or set NEVA_VAULT to the vault these notes are written into")

    index = _get_json(url, token, "/threads", opener, timeout)
    if not isinstance(index, dict) or not isinstance(index.get("threads"), list):
        raise ValueError("/threads field threads: expected an array; repair the worker response")
    pending = []
    seen = set()
    for position, head in enumerate(index["threads"]):
        if not isinstance(head, dict) or not isinstance(head.get("id"), str) or not head["id"]:
            raise ValueError("/threads field threads[{}].id: expected a nonempty string".format(position))
        thread_id = head["id"]
        if thread_id in seen:
            raise ValueError("/threads field id: duplicate thread ID")
        seen.add(thread_id)
        endpoint = "/threads/" + urllib.parse.quote(thread_id, safe="")
        thread = _get_json(url, token, endpoint, opener, timeout)
        if not isinstance(thread, dict) or thread.get("id") != thread_id:
            raise ValueError(endpoint + " field id: expected the requested thread ID")
        if not isinstance(thread.get("messages"), list):
            raise ValueError(endpoint + " field messages: expected an array")
        if "title" in thread and not isinstance(thread["title"], str):
            raise ValueError(endpoint + " field title: expected a string")
        for position, message in enumerate(thread["messages"]):
            field = endpoint + " field messages[{}].".format(position)
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant", "system", "tool"):
                raise ValueError(field + "role: expected user, assistant, system or tool")
            if not isinstance(message.get("content"), str):
                raise ValueError(field + "content: expected a string")
            if message.get("model") is not None and not isinstance(message["model"], str):
                raise ValueError(field + "model: expected a string or null")
        path = _thread_path(vault, thread)
        _check_ownership(path, thread)
        pending.append((path, thread_markdown(thread)))
    return [atomic_write(vault, path, markdown) for path, markdown in pending]
