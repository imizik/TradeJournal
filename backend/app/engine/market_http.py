"""Connection reuse for chart market-data reads; callers still own budgets,
cache keys, timeouts, retries and credentials. No response cache or cookie reuse."""
import atexit
import threading
import httpx

_lock = threading.Lock()
_client: httpx.Client | None = None


def get(url: str, **kwargs) -> httpx.Response:
    global _client
    with _lock:
        if _client is None:
            _client = httpx.Client(limits=httpx.Limits(max_connections=8, max_keepalive_connections=8, keepalive_expiry=30))
        client = _client
    # Explicit requests avoid persisting provider cookies between requests.
    headers = client.headers.copy()  # retain compression / keep-alive defaults
    headers.update(kwargs.pop("headers", None) or {})
    request = httpx.Request("GET", url, params=kwargs.pop("params", None), headers=headers)
    timeout = httpx.Timeout(kwargs.pop("timeout", 10))
    request.extensions["timeout"] = timeout.as_dict()
    return client.send(request, **kwargs)


def close() -> None:
    global _client
    with _lock:
        client, _client = _client, None
    if client is not None:
        client.close()


atexit.register(close)
