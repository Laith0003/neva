"""Atomic writes confined to a root, with descriptor-relative symlink refusal."""
import os
import secrets
import stat


def atomic_write(root, path, text):
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(root)))
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    for candidate in (root, path):
        current = os.path.sep
        for part in candidate.split(os.path.sep)[1:]:
            current = os.path.join(current, part)
            if os.path.islink(current):
                raise ValueError("symlink at {}: restore a regular file or directory".format(current))
    resolved_root, resolved_path = os.path.realpath(root), os.path.realpath(path)
    if os.path.commonpath((resolved_root, resolved_path)) != resolved_root:
        raise ValueError("output {} escapes root {}: choose a path inside the root".format(path, root))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(os.path.sep, flags)
    temporary = None
    try:
        for part in os.path.dirname(path).split(os.path.sep)[1:]:
            try:
                os.mkdir(part, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        leaf = os.path.basename(path)
        try:
            info = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if info is not None and not stat.S_ISREG(info.st_mode):
            raise ValueError("symlink or nonregular output {}: restore a regular file".format(path))
        candidate = ".neva-" + secrets.token_hex(16)
        fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        temporary = candidate
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)
    return path
