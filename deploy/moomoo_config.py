#!/usr/bin/env python3
"""Provision the manual moomoo bridge without enabling or starting it."""

import argparse
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

CONFIG = Path("/etc/tradejournal")
CREDENTIALS = CONFIG / "moomoo"
BRIDGE_ENV = CONFIG / "moomoo-bridge.env"
FRONTEND_ENV = CONFIG / "moomoo-frontend.env"
APPKEY_NAME = "appkey"
PRIVATE_KEY_NAME = "phase1-ed25519.pem"


def validate_origin(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    labels = host.split(".")
    valid_labels = all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in labels)
    if (parsed.scheme != "https" or not valid_labels or not host.endswith(".ts.net")
            or parsed.netloc != host or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Web origin must be a canonical private HTTPS *.ts.net origin")
    return f"https://{host}"


def read_source(path: Path, *, key: bool = False) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("Credential sources must be regular files with mode 0600 or stricter")
        data = source.read(16385)
    if not data or len(data) > 16384:
        raise ValueError("Credential source is empty or too large")
    if key:
        try:
            parsed = serialization.load_pem_private_key(data, password=None)
        except (TypeError, ValueError):
            raise ValueError("Private key source is not a valid unencrypted PEM key") from None
        if not isinstance(parsed, Ed25519PrivateKey):
            raise ValueError("Private key source must contain an Ed25519 private key")
    if not key and not re.fullmatch(rb"[A-Za-z0-9_-]{1,256}\s*", data):
        raise ValueError("AppKey source has an invalid format")
    return data


def atomic_secret(path: Path, content: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(path, mode)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def provision(appkey_source: Path, private_key_source: Path, origin: str) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Run with sudo")
    origin = validate_origin(origin)
    appkey = read_source(appkey_source)
    private_key = read_source(private_key_source, key=True)
    targets = (CREDENTIALS, BRIDGE_ENV, FRONTEND_ENV)
    if any(path.exists() or path.is_symlink() for path in targets):
        raise FileExistsError("Moomoo credentials or configuration already exist; refusing to overwrite")
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    created: list[Path] = []
    try:
        try:
            pwd.getpwnam("tradejournal-moomoo")
        except KeyError:
            subprocess.run([
                "useradd", "--system", "--user-group", "--no-create-home",
                "--shell", "/usr/sbin/nologin", "tradejournal-moomoo",
            ], check=True)
            pwd.getpwnam("tradejournal-moomoo")
        # Keep source keys root-only; systemd LoadCredential copies them into
        # the service's private runtime credential directory.
        CREDENTIALS.mkdir(mode=0o700)
        created.append(CREDENTIALS)
        atomic_secret(CREDENTIALS / APPKEY_NAME, appkey, 0o600)
        created.append(CREDENTIALS / APPKEY_NAME)
        atomic_secret(CREDENTIALS / PRIVATE_KEY_NAME, private_key, 0o600)
        created.append(CREDENTIALS / PRIVATE_KEY_NAME)
        token = secrets.token_urlsafe(32)
        atomic_secret(BRIDGE_ENV, (
            f"TJ_MOOMOO_LAB_TOKEN={token}\n"
            f"TJ_MOOMOO_CREDENTIAL_DIR={CREDENTIALS}\n"
        ).encode(), 0o600)
        created.append(BRIDGE_ENV)
        atomic_secret(FRONTEND_ENV, (
            f"TJ_MOOMOO_LAB_TOKEN={token}\n"
            "TJ_MOOMOO_LAB_ENABLED=true\n"
            f"TJ_MOOMOO_WEB_ORIGIN={origin}\n"
        ).encode(), 0o600)
        created.append(FRONTEND_ENV)
    except BaseException:
        for path in reversed(created):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        raise
    print("Moomoo credentials and root-private configuration provisioned. Service activation remains manual.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appkey-file", type=Path, required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--web-origin", required=True)
    args = parser.parse_args()
    try:
        provision(args.appkey_file, args.private_key_file, args.web_origin)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
