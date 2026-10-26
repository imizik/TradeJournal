"""The secrets check the copilot tests share: incidental digits are not a leak, a real account number or id is."""
import json
from uuid import UUID

from tests.secret_scan import leaks

ROTH = UUID(int=1)
SECRETS = ("8267", "4242", "RH-55501234", str(ROTH))


def test_digits_inside_a_uuid_or_a_timestamp_are_not_a_leak():
    text = json.dumps({"id": "1a2b8267-0c4d-4e5f-8267-4242abcdef01", "updated_at": "2026-10-26T04:08:22.042422Z",
                       "saved_at": "2026-10-25T00:22:12.826757+00:00", "opened_at": 1792768267})
    assert "8267" in text and "4242" in text  # a raw substring check would call this a leak
    assert leaks(text, SECRETS) == []


def test_a_leaked_account_number_label_or_id_is_caught():
    assert leaks(json.dumps({"last4": "8267"}), SECRETS) == ["8267"]
    assert leaks(json.dumps({"account": "Robinhood Roth 8267"}), SECRETS) == ["8267"]
    assert leaks(json.dumps({"note": "Webull ··4242 is dormant"}), SECRETS) == ["4242"]
    assert leaks(json.dumps({"broker_account_id": "RH-55501234"}), SECRETS) == ["RH-55501234"]
    assert leaks(json.dumps({"account_id": str(ROTH)}), SECRETS) == [str(ROTH)]
    assert leaks(json.dumps({"account_id": str(ROTH).upper()}), SECRETS) == [str(ROTH)]
