"""Generate a narrow nftables output policy for journal publisher credentials."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from ipaddress import IPv4Address, IPv6Address

_MAX_UID = 2**31 - 1
_IPV4_BLOCKS = (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4",
)
_IPV6_BLOCKS = ("::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8")


def _uid(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= _MAX_UID:
        raise ValueError("publisher UIDs must be distinct canonical integers in range")
    return value


def _addresses(values: list[str], label: str) -> tuple[list[IPv4Address | IPv6Address], list[IPv4Address | IPv6Address]]:
    if not isinstance(values, list):
        raise TypeError(f"{label} must be a list of canonical IP literals")
    parsed: dict[int, IPv4Address | IPv6Address] = {}
    for value in values:
        if not isinstance(value, str) or "%" in value:
            raise ValueError(f"{label} must contain canonical IP literals")
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(f"{label} must contain canonical IP literals") from exc
        if str(address) != value:
            raise ValueError(f"{label} must contain canonical IP literals")
        parsed[address.version * (2**128) + int(address)] = address
    ordered = sorted(parsed.values(), key=lambda address: (address.version, int(address)))
    return ([address for address in ordered if address.version == 4],
            [address for address in ordered if address.version == 6])


def _set(values: Sequence[object]) -> str:
    return "{ " + ", ".join(map(str, values)) + " }"


def nft_policy(export_uid: int, key_uid: int, dns_servers: list[str], host_ips: list[str]) -> str:
    """Return static rules for the two publisher UIDs, without touching other UIDs."""
    export_uid, key_uid = _uid(export_uid), _uid(key_uid)
    if export_uid == key_uid:
        raise ValueError("publisher UIDs must be distinct canonical integers in range")
    lines = [
        "table inet tj_journal_publishers {",
        "    chain output {",
        "        type filter hook output priority -50; policy accept;",
        f"        meta skuid {export_uid} ip daddr 127.0.0.1 tcp dport 5432 accept",
        f"        meta skuid {export_uid} meta nfproto ipv4 drop",
        f"        meta skuid {export_uid} meta nfproto ipv6 drop",
        *_key_rules(key_uid, dns_servers, host_ips),
        "    }",
        "}",
    ]
    return "\n".join(lines) + "\n"


def key_policy(key_uid: int, dns_servers: list[str], host_ips: list[str]) -> str:
    """Return the same public-key-only rules for the advisor key publisher UID."""
    lines = [
        "table inet tj_advisor_keys {",
        "    chain output {",
        "        type filter hook output priority -50; policy accept;",
        *_key_rules(_uid(key_uid), dns_servers, host_ips),
        "    }",
        "}",
    ]
    return "\n".join(lines) + "\n"


def _key_rules(key_uid: int, dns_servers: list[str], host_ips: list[str]) -> list[str]:
    """DNS to the named resolvers and public HTTPS only; private/host addresses denied."""
    dns4, dns6 = _addresses(dns_servers, "DNS servers")
    if not dns4 and not dns6:
        raise ValueError("at least one DNS server is required")
    host4, host6 = _addresses(host_ips, "host IPs")

    v4_blocked = [ipaddress.ip_network(value) for value in _IPV4_BLOCKS] + host4
    v6_blocked = [ipaddress.ip_network(value) for value in _IPV6_BLOCKS] + host6
    lines = []
    if dns4:
        dns_set = _set(dns4)
        lines.extend((
            f"        meta skuid {key_uid} ip daddr {dns_set} udp dport 53 accept",
            f"        meta skuid {key_uid} ip daddr {dns_set} tcp dport 53 accept",
        ))
    if dns6:
        dns_set = _set(dns6)
        lines.extend((
            f"        meta skuid {key_uid} ip6 daddr {dns_set} udp dport 53 accept",
            f"        meta skuid {key_uid} ip6 daddr {dns_set} tcp dport 53 accept",
        ))
    lines.extend((
        f"        meta skuid {key_uid} ip daddr { _set(v4_blocked) } drop",
        f"        meta skuid {key_uid} ip6 daddr { _set(v6_blocked) } drop",
        f"        meta skuid {key_uid} meta nfproto ipv4 tcp dport 443 accept",
        f"        meta skuid {key_uid} meta nfproto ipv6 tcp dport 443 accept",
        f"        meta skuid {key_uid} meta nfproto ipv4 drop",
        f"        meta skuid {key_uid} meta nfproto ipv6 drop",
    ))
    return lines
