"""Public-key snapshot freshness, shared by root key upkeep and the owner reader.

Standard library only: the root operator runs it with the system interpreter.
States and timestamps leave; key material never does.
"""
import json
import os
import stat
import time

FRESH_MARGIN = 15 * 60
MAX_SNAPSHOT = 64 * 1024


def read_snapshot(path, *, owner=None):
    """Read a public snapshot without following links or blocking on special files.

    The key UID owns the maintained directory, so root must not trust its leaf:
    require a small regular file (owned by the key UID when given) that parses.
    """
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or (owner is not None and info.st_uid != owner):
            raise ValueError("Public-key snapshot must be a regular file owned by its publisher")
        body = os.read(descriptor, MAX_SNAPSHOT + 1)
    finally:
        os.close(descriptor)
    if len(body) > MAX_SNAPSHOT:
        raise ValueError("Public-key snapshot is too large")
    snapshot = json.loads(body)
    if (not isinstance(snapshot, dict) or set(snapshot) != {"issuer_url", "jwks_url", "fetched_at", "expires_at", "keys"}
            or not isinstance(snapshot["keys"], list)):
        raise ValueError("Not a public-key snapshot")
    return body, snapshot


def snapshot_state(config, *, now=None):
    """Public freshness facts only; never key material."""
    now = time.time() if now is None else now
    try:
        _, snapshot = read_snapshot(config["jwks_file"])
        expires = int(snapshot["expires_at"])
        matches = snapshot["issuer_url"] == config["issuer_url"] and snapshot["jwks_url"] == config["jwks_url"]
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unreadable", "expires_at": None}
    if not matches:
        state = "issuer-mismatch"
    elif now >= expires:
        state = "expired"
    elif expires - now <= FRESH_MARGIN:
        state = "expiring"
    else:
        state = "fresh"
    return {"state": state, "expires_at": expires, "seconds_left": max(0, int(expires - now))}
