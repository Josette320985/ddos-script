#!/usr/bin/env python3
"""Bounded HTTP load test for the Fail2ban lab.

Usage:
    python flood.py --host <host> --port <port> [--duration N] [--concurrency N] [--rps N]
    python flood.py --target http://192.168.1.10:8081 --duration 30

Examples:
    python flood.py --host localhost --port 5173
    python flood.py --host localhost --port 8001 --duration 60 --concurrency 100
    python flood.py --target http://localhost:8081
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

DEFAULT_DURATION = 20
DEFAULT_CONCURRENCY = 40
DEFAULT_REQUESTS_PER_SECOND = 50

MAX_DURATION_SECONDS = 300
MAX_CONCURRENCY = 500
MAX_REQUESTS_PER_SECOND = 500

REQUEST_TIMEOUT_SECONDS = 2
REPORT_INTERVAL_SECONDS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded HTTP load test for the Fail2ban lab.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", type=str, default=None,
                        help="Target host (e.g. localhost)")
    parser.add_argument("--port", type=int, default=None,
                        help="Target port (e.g. 5173)")
    parser.add_argument("--target", type=str, default=None,
                        help="Full target URL (alternative to --host/--port)")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Duration per target in seconds (max {MAX_DURATION_SECONDS})")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"Parallel workers (max {MAX_CONCURRENCY})")
    parser.add_argument("--rps", type=int, default=DEFAULT_REQUESTS_PER_SECOND,
                        help=f"Max requests per second (max {MAX_REQUESTS_PER_SECOND})")
    parser.add_argument("--path", type=str, default="/",
                        help="Path to request (default: /)")
    return parser.parse_args()


def validate_bounds(name: str, value: int, maximum: int) -> int:
    if not 1 <= value <= maximum:
        raise SystemExit(f"{name} must be between 1 and {maximum}; got {value}")
    return value


def build_target_url(args: argparse.Namespace) -> str:
    if args.target:
        return args.target.rstrip("/")
    host = args.host or os.environ.get("TARGET_HOST", "localhost")
    port = args.port or int(os.environ.get("TARGET_PORT", 80))
    scheme = "https" if port in (443, 8443) else "http"
    return f"{scheme}://{host}:{port}"


def request_status(opener: urllib.request.OpenerDirector, url: str) -> str:
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return str(response.status)
    except urllib.error.HTTPError as error:
        return str(error.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return "000"


class RateLimiter:
    def __init__(self, requests_per_second: int) -> None:
        self.interval = 1 / requests_per_second
        self.next_request_at = 0.0
        self.lock = threading.Lock()

    def wait_for_turn(self, stop_event: threading.Event) -> bool:
        with self.lock:
            now = time.monotonic()
            scheduled_at = max(now, self.next_request_at)
            self.next_request_at = scheduled_at + self.interval
        return not stop_event.wait(max(0.0, scheduled_at - now))


def worker(url, deadline, stop_event, rate_limiter, counts, counts_lock):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while not stop_event.is_set() and time.monotonic() < deadline:
        if not rate_limiter.wait_for_turn(stop_event):
            break
        if time.monotonic() >= deadline:
            break
        code = request_status(opener, url)
        with counts_lock:
            counts[code] += 1


def snapshot(counts, counts_lock):
    with counts_lock:
        return counts.copy()


def report(url, counts, final=False):
    total = sum(counts.values())
    ok = counts["200"]
    failed = total - ok
    label = "RESULT" if final else f"[{datetime.now():%H:%M:%S}] partial"
    print(f"  {label} for {url}: total={total} ok(200)={ok} blocked/failed={failed}",
          flush=True)
    if final and total:
        print(f"  -> {failed * 100 // total}% of responses were non-200", flush=True)


def run_target(url, concurrency, duration, rps):
    print(f"\n--- Target: {url} ({concurrency} workers, {rps} req/s max, {duration}s) ---",
          flush=True)
    counts = Counter()
    counts_lock = threading.Lock()
    stop_event = threading.Event()
    rate_limiter = RateLimiter(rps)
    deadline = time.monotonic() + duration
    interrupted = False

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(worker, url, deadline, stop_event,
                            rate_limiter, counts, counts_lock)
            for _ in range(concurrency)
        ]
        try:
            while time.monotonic() < deadline:
                time.sleep(min(REPORT_INTERVAL_SECONDS, deadline - time.monotonic()))
                report(url, snapshot(counts, counts_lock))
        except KeyboardInterrupt:
            interrupted = True
            stop_event.set()
            print("\nStopping workers after Ctrl-C...", flush=True)
        finally:
            stop_event.set()
        for future in futures:
            future.result()
    report(url, snapshot(counts, counts_lock), final=True)
    return not interrupted


def main() -> None:
    args = parse_args()
    duration = validate_bounds("duration", args.duration, MAX_DURATION_SECONDS)
    concurrency = validate_bounds("concurrency", args.concurrency, MAX_CONCURRENCY)
    rps = validate_bounds("rps", args.rps, MAX_REQUESTS_PER_SECOND)

    base_url = build_target_url(args)
    url = base_url + args.path

    print(f"=== Bounded HTTP lab test: {concurrency} workers, "
          f"up to {rps} req/s, {duration}s per target ===", flush=True)
    print(f"=== Target URL: {url} ===\n", flush=True)

    run_target(url, concurrency, duration, rps)

    print("\n=== Test finished. ===")
    print("A non-200 result can be a ban, an HTTP error, or a connection timeout.")


if __name__ == "__main__":
    main()
