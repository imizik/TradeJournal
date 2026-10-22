"""Diagnostics must not change locking or leak timings between requests."""
import threading

from fastapi import Response
import pytest

from app.engine import chart_timing as timing


def test_lock_wait_excludes_work_and_releases_on_failure(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(timing.time, 'perf_counter', lambda: now[0])
    class Lock:
        released = False
        def acquire(self):
            now[0] += .25
        def release(self):
            self.released = True
    lock, response = Lock(), Response()
    with pytest.raises(ValueError), timing.request_timing(True, response):
        with timing.measured_lock(lock, 'history_queue'):
            now[0] += 2
            raise ValueError('fixture')
    assert lock.released
    assert response.headers['server-timing'] == 'history_queue;dur=250.000, total;dur=2250.000'
    assert timing._current.get() is None


def test_disabled_and_concurrent_requests_are_isolated():
    gate = threading.Barrier(2)
    def run(enabled):
        response = Response()
        with timing.request_timing(enabled, response):
            with timing.measured('provider'):
                gate.wait(timeout=2)
        return response.headers.get('server-timing')
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:
        on, off = pool.submit(run, True), pool.submit(run, False)
        assert 'provider;dur=' in on.result()
        assert off.result() is None
