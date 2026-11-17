"""Helpers for AF_UNIX socket paths.

Linux stores UNIX socket paths in ``struct sockaddr_un.sun_path`` (108 bytes,
including the terminating NUL).  Paths longer than that cannot be bound or
connected to.  qemu-compose keeps its state below ``XDG_DATA_HOME`` and adds a
32 character VM id plus the socket name, which can easily overflow this limit
in production deployments that use a deep data directory.

``unix_socket_path`` keeps sockets inside the instance directory whenever they
fit.  Otherwise it redirects them to a short, per-user runtime directory.  The
mapping is deterministic so a later command (for example ``qemu-compose
monitor``) can derive the same path from the instance directory alone.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile

# Linux: offsetof(struct sockaddr_un, sun_path) + strlen(path) must be shorter
# than sizeof(sun_path).  Stay one byte below the raw buffer size.
SUN_PATH_MAX = 108


def unix_socket_path_fits(path: str) -> bool:
    """Return True if *path* can be used as an AF_UNIX socket path."""
    return len(os.fsencode(path)) < SUN_PATH_MAX


def _runtime_dir_candidates() -> list:
    candidates = []
    xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime_dir:
        candidates.append(xdg_runtime_dir)
    tmpdir = tempfile.gettempdir()
    if tmpdir:
        candidates.append(tmpdir)
    if "/tmp" not in candidates:
        candidates.append("/tmp")
    return candidates


def _short_socket_roots(base_dir: str) -> list:
    """Create and return private, deterministic socket directories.

    One directory is produced per usable runtime root.  ``unix_socket_path``
    picks the first one that can hold the socket name, preferring
    ``XDG_RUNTIME_DIR`` but falling back to /tmp when that path is itself too
    long for AF_UNIX (for example in some CI or container setups).
    """
    uid = os.getuid()
    digest = hashlib.sha256(
        os.path.abspath(base_dir).encode("utf-8", "surrogateescape")
    ).hexdigest()[:16]

    roots = []
    errors = []
    for runtime_dir in _runtime_dir_candidates():
        if not os.path.isdir(runtime_dir):
            errors.append("%s: not a directory" % runtime_dir)
            continue

        root = os.path.join(runtime_dir, "qemu-compose-%d" % uid)
        try:
            if os.path.islink(root):
                raise OSError("refusing to use symlinked runtime directory")
            os.makedirs(root, mode=0o700, exist_ok=True)
            st = os.stat(root)
            if st.st_uid != uid:
                raise OSError("runtime directory is owned by another user")
            os.chmod(root, 0o700)

            socket_dir = os.path.join(root, digest)
            if os.path.islink(socket_dir):
                raise OSError("refusing to use symlinked socket directory")
            os.makedirs(socket_dir, mode=0o700, exist_ok=True)
            st = os.stat(socket_dir)
            if st.st_uid != uid:
                raise OSError("socket directory is owned by another user")
            os.chmod(socket_dir, 0o700)
            roots.append(socket_dir)
        except OSError as error:
            errors.append("%s: %s" % (runtime_dir, error))

    if not roots:
        raise OSError(
            "unable to create a private runtime directory for UNIX sockets: %s"
            % "; ".join(errors)
        )
    return roots


def unix_socket_path(base_dir: str, name: str) -> str:
    """Return a usable AF_UNIX socket path for ``base_dir/name``.

    Short paths are returned unchanged.  For long paths the socket lives in a
    private runtime directory instead; the result is stable for a given
    *base_dir* and *name*.
    """
    name = os.path.basename(name)
    preferred = os.path.join(base_dir, name)
    if unix_socket_path_fits(preferred):
        return preferred

    short_dirs = _short_socket_roots(base_dir)
    for short_dir in short_dirs:
        candidate = os.path.join(short_dir, name)
        if unix_socket_path_fits(candidate):
            return candidate

    # Last resort for absurdly long socket names: keep a readable prefix and
    # append a short digest so different names still map to different paths.
    short_dir = min(short_dirs, key=lambda path: len(os.fsencode(path)))
    stem, ext = os.path.splitext(name)
    digest = hashlib.sha256(name.encode("utf-8", "surrogateescape")).hexdigest()[:8]
    budget = SUN_PATH_MAX - 1 - len(os.fsencode(short_dir)) - 1 - len(ext) - 1 - len(digest)
    if budget < 0:
        raise OSError(
            "AF_UNIX socket path is too long even in the runtime directory: %s"
            % candidate
        )
    stem = stem[:budget]
    candidate = os.path.join(short_dir, "%s-%s%s" % (stem, digest, ext))
    if not unix_socket_path_fits(candidate):
        raise OSError("AF_UNIX socket path is too long: %s" % candidate)
    return candidate


def cleanup_unix_socket_dir(base_dir: str) -> None:
    """Remove the runtime socket directory derived from *base_dir*, if any.

    Sockets in the instance directory are removed together with the instance
    itself and are deliberately left alone here.
    """
    uid = os.getuid()
    digest = hashlib.sha256(
        os.path.abspath(base_dir).encode("utf-8", "surrogateescape")
    ).hexdigest()[:16]
    for runtime_dir in _runtime_dir_candidates():
        if not os.path.isdir(runtime_dir):
            continue
        root = os.path.join(runtime_dir, "qemu-compose-%d" % uid)
        socket_dir = os.path.join(root, digest)
        if os.path.isdir(socket_dir):
            shutil.rmtree(socket_dir, ignore_errors=True)
        # Best effort: remove the per-user root once it is empty.
        try:
            os.rmdir(root)
        except OSError:
            pass
