"""Which secrets leaked into a payload's text.

A raw substring check gives false hits: "8267" sits inside random UUIDs and microsecond timestamps
("04:08:22.826757Z"). Here a UUID counts only as a whole UUID, and any other secret only as a whole word, so "Roth 8267",
"last4":"8267" and an account's id still leak while those incidental digits do not. JSON text is read with its escapes
decoded, so "\\u00b7\\u00b78267" (a dumped "··8267") is still "8267" as a word.
"""
import json
import re

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def leaks(text: str, secrets) -> list[str]:
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False)
    except ValueError:
        pass
    uuids = {match.lower() for match in _UUID.findall(text)}
    rest = _UUID.sub(" ", text)
    return [secret for secret in secrets
            if (secret.lower() in uuids if _UUID.fullmatch(secret)
                else re.search(rf"(?<![0-9A-Za-z]){re.escape(secret)}(?![0-9A-Za-z])", rest))]
