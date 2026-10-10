"""Continuous templates preserve the credential and process boundary."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("journal_scope", ROOT / "deploy/journal_coach_scope.py")
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


def test_account_view_is_projection_and_calendar_bound_not_a_role_membership():
    sql = scope.scoped_view_sql("00000000-0000-4000-8000-000000000001")
    assert "security_barrier=true" in sql and "America/New_York" in sql
    assert "::date - 29" in sql and "::date + 1" in sql
    assert "status IN ('closed', 'expired')" in sql
    assert "REVOKE SELECT ON public.trade" in sql
    assert "GRANT SELECT ON public.journal_coach_export_trade" in sql
    assert "OR REPLACE" not in sql and "LOGIN" not in sql
    assert "notes" not in sql and "email" not in sql


@pytest.mark.parametrize("account,days", [("invalid",30),("00000000-0000-4000-8000-000000000001';DROP TABLE trade",30),("00000000-0000-4000-8000-000000000001",True),("00000000-0000-4000-8000-000000000001",32)])
def test_invalid_scope_cannot_generate_sql(account,days):
    with pytest.raises(ValueError):
        scope.scoped_view_sql(account,days)


def test_export_and_public_key_publishers_have_distinct_minimum_access():
    units = ROOT / "deploy/cloud-mcp-journal"
    exporter = (units / "tradejournal-journal-export.service").read_text()
    keys = (units / "tradejournal-journal-real-keys.service").read_text()
    serving = (units / "tradejournal-journal-coach.service").read_text()
    assert "LoadCredential=database-url:" in exporter
    assert "LoadCredential=scope.json:" in exporter
    assert "IPAddressDeny=any" in exporter and "IPAddressAllow=localhost" in exporter
    assert "RestrictAddressFamilies=AF_INET" in exporter
    assert "ReadWritePaths=/var/lib/tradejournal-journal-real/publication" in exporter
    assert "export-database-url" in keys and "LoadCredential" not in keys
    assert "ReadWritePaths=/var/lib/tradejournal-journal-real/public-keys" in keys
    assert "PrivateNetwork=true" in serving and "LoadCredential" not in serving
    assert "ReadWritePaths" not in serving
    for text in (exporter,keys):
        assert "NoNewPrivileges=true" in text and "ProtectSystem=strict" in text
        assert "Requires=tradejournal-journal-network.service" in text
        assert "CapabilityBoundingSet=\n" in text and "EnvironmentFile" not in text
    for name in ("tradejournal-journal-export.timer","tradejournal-journal-real-keys.timer"):
        text = (units / name).read_text()
        assert "OnUnitActiveSec=15min" in text and "OnBootSec=30s" in text


def test_network_policy_unit_owns_only_its_table_and_has_no_ip_socket_family():
    text = (ROOT / "deploy/cloud-mcp-journal/tradejournal-journal-network.service").read_text()
    assert "ExecStop=/usr/sbin/nft delete table inet tj_journal_publishers" in text
    assert "CapabilityBoundingSet=CAP_NET_ADMIN" in text
    assert "RestrictAddressFamilies=AF_NETLINK AF_UNIX" in text
    assert "flush ruleset" not in text.lower().replace("# never flush the host ruleset.", "")
