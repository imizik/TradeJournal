from __future__ import annotations

import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
sys.path.insert(0, str(DEPLOY))

from journal_coach_network import nft_policy  # noqa: E402


def test_policy_is_scoped_to_two_uids_and_one_new_accepting_output_chain():
    policy = nft_policy(210, 211, ["1.1.1.1", "2001:4860:4860::8888"], ["203.0.113.7"])
    assert policy.startswith("table inet tj_journal_publishers {")
    assert "type filter hook output priority -50; policy accept;" in policy
    assert "flush ruleset" not in policy
    assert all(line.strip().startswith("meta skuid") or line.strip() in {
        "table inet tj_journal_publishers {", "chain output {",
        "type filter hook output priority -50; policy accept;", "}",
    } for line in policy.splitlines())
    assert "meta skuid 210 ip daddr 127.0.0.1 tcp dport 5432 accept" in policy
    assert "meta skuid 210 meta nfproto ipv4 drop" in policy
    assert "meta skuid 210 meta nfproto ipv6 drop" in policy
    assert "meta skuid 211 meta nfproto ipv4 tcp dport 443 accept" in policy
    assert "meta skuid 211 meta nfproto ipv6 tcp dport 443 accept" in policy
    # Unmatched UIDs see only this base chain's accept policy.
    assert all(line.strip().startswith("meta skuid") for line in policy.splitlines()
               if line.strip().endswith((" accept", " drop")))


def test_dns_exceptions_are_exact_family_specific_and_precede_blocked_ranges():
    policy = nft_policy(210, 211, ["127.0.0.1", "2001:4860:4860::8888"], [])
    dns4_udp = "meta skuid 211 ip daddr { 127.0.0.1 } udp dport 53 accept"
    dns4_tcp = "meta skuid 211 ip daddr { 127.0.0.1 } tcp dport 53 accept"
    dns6_udp = "meta skuid 211 ip6 daddr { 2001:4860:4860::8888 } udp dport 53 accept"
    dns6_tcp = "meta skuid 211 ip6 daddr { 2001:4860:4860::8888 } tcp dport 53 accept"
    blocked4 = "meta skuid 211 ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8"
    blocked6 = "meta skuid 211 ip6 daddr { ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8"
    for allowed in (dns4_udp, dns4_tcp, dns6_udp, dns6_tcp):
        assert allowed in policy
    assert policy.index(dns4_udp) < policy.index(blocked4)
    assert policy.index(dns6_udp) < policy.index(blocked6)
    assert "dport 53" not in policy[policy.index(blocked4):]


def test_reserved_and_exact_host_ips_are_denied_before_https_allow():
    policy = nft_policy(210, 211, ["9.9.9.9"], ["8.8.8.8", "2001:4860::1"])
    blocked4 = next(line for line in policy.splitlines() if "meta skuid 211 ip daddr" in line and "drop" in line)
    blocked6 = next(line for line in policy.splitlines() if "meta skuid 211 ip6 daddr" in line and "drop" in line)
    https4 = "meta skuid 211 meta nfproto ipv4 tcp dport 443 accept"
    https6 = "meta skuid 211 meta nfproto ipv6 tcp dport 443 accept"
    assert "8.8.8.8" in blocked4 and "2001:4860::1" in blocked6
    assert policy.index(blocked4) < policy.index(https4)
    assert policy.index(blocked6) < policy.index(https6)
    assert "ip daddr { 9.9.9.9 } udp dport 53 accept" in policy
    assert "ip daddr { 9.9.9.9 } tcp dport 53 accept" in policy
    assert "ip daddr { 9.9.9.9 } tcp dport 443 accept" not in policy


@pytest.mark.parametrize(("export_uid", "key_uid"), [
    (True, 101), (101, False), (99, 101), (101, 2**31), (101.0, 102), (101, 101),
])
def test_invalid_or_equal_uids_are_rejected(export_uid, key_uid):
    with pytest.raises(ValueError):
        nft_policy(export_uid, key_uid, ["1.1.1.1"], [])


@pytest.mark.parametrize("value", [
    "dns.example", "1.1.1.1; flush ruleset", "01.1.1.1", "2001:4860:0:0::8888", "fe80::1%en0",
])
def test_noncanonical_or_injected_ips_are_rejected(value):
    with pytest.raises(ValueError):
        nft_policy(210, 211, [value], [])


@pytest.mark.parametrize("values", ["1.1.1.1", ["1.1.1.1", 53], ["1.1.1.1/32"], []])
def test_invalid_dns_list_is_rejected(values):
    with pytest.raises((ValueError, TypeError)):
        nft_policy(210, 211, values, [])


@pytest.mark.parametrize("value", ["127.0.0.1/32", "10.0.0.1; drop", 53])
def test_invalid_host_ip_is_rejected(value):
    with pytest.raises(ValueError):
        nft_policy(210, 211, ["1.1.1.1"], [value])


def test_empty_host_list_and_dns_family_splitting_are_supported():
    policy = nft_policy(210, 211, ["2001:4860:4860::8888"], [])
    assert "meta skuid 211 ip6 daddr { 2001:4860:4860::8888 } udp dport 53 accept" in policy
    assert "meta skuid 211 ip daddr { 0.0.0.0/8" in policy
