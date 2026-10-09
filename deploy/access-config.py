#!/usr/bin/env python3
"""Generate private auth configuration files. Never enables internet access."""
import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit


def generate(directory: Path, owner_origin: str, assistant_origin: str, *, local_http=False, sample=False):
    for value in (owner_origin, assistant_origin):
        parsed = urlsplit(value)
        if value != f"{parsed.scheme}://{parsed.netloc}":
            raise ValueError("Use a canonical origin without whitespace or paths")
        if local_http and (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}):
            raise ValueError("Local HTTP mode is only for loopback fixtures")
        if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or not parsed.hostname or parsed.scheme != "https":
            if not (local_http and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and not parsed.path and not parsed.query and not parsed.fragment and not parsed.username and not parsed.password):
                raise ValueError("Use separate HTTPS origins, or explicit loopback-only HTTP fixtures")
    if owner_origin == assistant_origin:
        raise ValueError("Owner and assistant origins must be different")
    keys = {name: secrets.token_urlsafe(32) for name in ("owner", "assistant", "monitor", "automation", "manual_mcp")}
    common = f"TJ_ACCESS_ALLOW_LOCAL_HTTP={'true' if local_http else 'false'}\n"
    files = {
        "access-backend.env": f"TJ_ACCESS_ENABLED=true\nTJ_OWNER_GATEWAY_KEY={keys['owner']}\nTJ_ASSISTANT_GATEWAY_KEY={keys['assistant']}\nTJ_OWNER_ORIGIN={owner_origin}\nTJ_ASSISTANT_ORIGIN={assistant_origin}\nTJ_ACCESS_SAMPLE_DATA={'true' if sample else 'false'}\nTJ_ACCESS_SERVICES='{json.dumps({k: keys[k] for k in ('monitor', 'automation', 'manual_mcp')})}'\n" + common,
        "access-owner.env": f"TJ_ACCESS_PROFILE=owner\nTJ_GATEWAY_KEY={keys['owner']}\nTJ_WEB_ORIGIN={owner_origin}\n" + common,
        # An operator must approve the test/live entrance before changing this flag.
        "access-assistant.env": f"TJ_ACCESS_PROFILE=assistant\nTJ_ASSISTANT_ENABLED=false\nTJ_GATEWAY_KEY={keys['assistant']}\nTJ_WEB_ORIGIN={assistant_origin}\n" + common,
        "access-monitor.env": f"TJ_SERVICE_KEY={keys['monitor']}\n",
        "access-automation.env": f"TJ_SERVICE_KEY={keys['automation']}\n",
        "access-mcp.env": f"TRADE_JOURNAL_SERVICE_KEY={keys['manual_mcp']}\n",
    }
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any((directory / name).exists() for name in files):
        raise ValueError("Auth configuration already exists; refusing to replace credentials")
    created = []
    try:
        for name, content in files.items():
            path = directory / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "w") as target:
                target.write(content)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return list(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--owner-origin", required=True)
    parser.add_argument("--assistant-origin", required=True)
    parser.add_argument("--local-http", action="store_true")
    parser.add_argument("--sample-data", action="store_true")
    args = parser.parse_args()
    names = generate(args.directory, args.owner_origin, args.assistant_origin, local_http=args.local_http, sample=args.sample_data)
    print(f"Created {len(names)} private configuration files. Assistant entrance remains disabled. No secrets printed.")


if __name__ == "__main__":
    main()
