#!/usr/bin/env python3
"""Set up and switch the private app's owner lock (docs/owner-lock.md).

Run on the server as root with the release's Python:

    sudo /opt/tradejournal/current/backend/.venv/bin/python /opt/tradejournal/current/deploy/owner_lock_config.py status
    ... passphrase      make a new passphrase (prints it once; ends every signed-in device)
    ... mode report     sign-in works, nothing is refused, would-be refusals are logged
    ... mode on         refuse every browser request without the owner session
    ... mode off        the break-glass: the app behaves exactly as before the lock

Everything lives in /etc/tradejournal/owner-lock.env (root only, mode 0600),
which the API and frontend units load. The passphrase itself is never stored.
"""
import argparse
import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

from argon2 import PasswordHasher

CONFIG = Path("/etc/tradejournal")
FILE_NAME = "owner-lock.env"
SERVICES = ("tradejournal-api.service", "tradejournal-frontend.service")
MODES = ("off", "report", "on")
# The same Argon2id parameters the API verifies with (app/engine/access.py HASHER).
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
# No look-alike characters, so it can be typed from a printout if ever needed.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
HEADER = "# Owner lock (docs/owner-lock.md). Written by deploy/owner_lock_config.py; keep root-only, mode 0600.\n"


def new_passphrase(groups: int = 6, size: int = 5) -> str:
    """Six groups of five: about 147 bits, far beyond guessing even without the rate limit."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(size)) for _ in range(groups))


def encode_hash(passphrase: str) -> str:
    # base64 keeps the Argon2 "$" separators away from env-file parsers.
    return base64.urlsafe_b64encode(HASHER.hash(passphrase).encode()).decode().rstrip("=")


def read(path: Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip()
    return values


def write(path: Path, values: dict) -> None:
    body = HEADER + "".join(f"{name}={values[name]}\n" for name in
                            ("TJ_OWNER_LOCK", "TJ_OWNER_LOCK_PASSPHRASE_HASH", "TJ_OWNER_LOCK_LOCAL_KEY") if values.get(name))
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".owner-lock.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(body)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def restart(enabled: bool) -> None:
    if enabled:
        subprocess.run(["systemctl", "restart", *SERVICES], check=True)
        print("Restarted the app (API and web page).")
    else:
        print("Not restarted. The change takes effect after: sudo systemctl restart " + " ".join(SERVICES))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config-dir", type=Path, default=CONFIG, help=argparse.SUPPRESS)
    parser.add_argument("--no-restart", action="store_true", help="write the file but do not restart the app")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("passphrase")
    mode = commands.add_parser("mode")
    mode.add_argument("value", choices=MODES)
    args = parser.parse_args(argv)
    if args.config_dir == CONFIG and os.geteuid() != 0:
        print("Run this with sudo.", file=sys.stderr)
        return 2
    path = args.config_dir / FILE_NAME
    values = read(path)
    current = values.get("TJ_OWNER_LOCK", "off") or "off"

    if args.command == "status":
        print(f"Lock: {current}")
        print("Passphrase: " + ("set" if values.get("TJ_OWNER_LOCK_PASSPHRASE_HASH") else "not set"))
        print("Server key for the deploy check: " + ("set" if len(values.get("TJ_OWNER_LOCK_LOCAL_KEY", "")) >= 32 else "not set"))
        if path.exists() and path.stat().st_mode & 0o077:
            print(f"Warning: {path} can be read by other users; it should be mode 0600.")
        return 0

    if args.command == "passphrase":
        passphrase = new_passphrase()
        values["TJ_OWNER_LOCK"] = current
        values["TJ_OWNER_LOCK_PASSPHRASE_HASH"] = encode_hash(passphrase)
        if len(values.get("TJ_OWNER_LOCK_LOCAL_KEY", "")) < 32:
            values["TJ_OWNER_LOCK_LOCAL_KEY"] = secrets.token_urlsafe(32)
        write(path, values)
        print("Your new Trade Journal passphrase (shown once, never stored):\n")
        print("    " + passphrase + "\n")
        print("Save it in your password manager now. Every device signed in with an older passphrase")
        print("is signed out once the app restarts.")
        restart(current != "off" and not args.no_restart)
        return 0

    wanted = args.value
    if wanted != "off" and (not values.get("TJ_OWNER_LOCK_PASSPHRASE_HASH") or len(values.get("TJ_OWNER_LOCK_LOCAL_KEY", "")) < 32):
        print("Make a passphrase first: owner_lock_config.py passphrase", file=sys.stderr)
        return 1
    values["TJ_OWNER_LOCK"] = wanted
    write(path, values)
    print(f"Lock set to {wanted}.")
    restart(not args.no_restart)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
