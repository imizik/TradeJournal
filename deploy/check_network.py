"""Generate the UID-only nftables policy for the pre-trade check identities."""

from __future__ import annotations

from journal_coach_network import _key_rules, _uid


def check_policy(service_uid: int, key_uid: int, features_uid: int, dns_servers: list[str], host_ips: list[str]) -> str:
    """Service and key UIDs: DNS + public HTTPS only. Features UID: local Postgres only.

    Private, loopback and this host's addresses are denied to the service UID,
    so the unauthenticated private API (8080/8000) and Postgres are unreachable.
    """
    uids = [_uid(service_uid), _uid(key_uid), _uid(features_uid)]
    if len(set(uids)) != 3:
        raise ValueError("check UIDs must be distinct")
    lines = [
        "table inet tj_check {",
        "    chain output {",
        "        type filter hook output priority -50; policy accept;",
        *_key_rules(service_uid, dns_servers, host_ips),
        *_key_rules(key_uid, dns_servers, host_ips),
        f"        meta skuid {features_uid} ip daddr 127.0.0.1 tcp dport 5432 accept",
        f"        meta skuid {features_uid} meta nfproto ipv4 drop",
        f"        meta skuid {features_uid} meta nfproto ipv6 drop",
        "    }",
        "}",
    ]
    return "\n".join(lines) + "\n"
