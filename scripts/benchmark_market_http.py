#!/usr/bin/env python3
"""Offline transport comparison. No credentials, provider calls or trading data.
Measures local HTTP/1.1 reuse, NOT expected production/TLS latency savings.
Run with the backend virtualenv Python from the repository root.
"""
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
from app.engine import market_http

connections = set()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def do_GET(self):
        connections.add(self.client_address)
        body = b'{"bars": []}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/bars"
    result = {"environment": "local HTTP/1.1, no TLS/provider, 5 trials of 12 sequential reads", "trials": {}}
    try:
        for name, get in (("before", httpx.get), ("pooled", market_http.get)):
            trials = []
            for _ in range(5):
                market_http.close()
                connections.clear()
                start = time.perf_counter()
                for _ in range(12):
                    assert get(url, timeout=5).json() == {"bars": []}
                trials.append({"ms": round((time.perf_counter() - start) * 1000, 3), "connections": len(connections)})
            result["trials"][name] = trials
        print(json.dumps(result, indent=2))
    finally:
        market_http.close()
        server.shutdown()
        server.server_close()
