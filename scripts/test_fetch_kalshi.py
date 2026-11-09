"""Offline checks for public API pacing, caching, and throttling."""

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import fetch_kalshi as fetch


class FetchTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".cache"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        fetch._last_request_started = None

    def test_serialized_spacing_and_cache(self):
        clock = [100.0]
        starts = []

        def open_url(*args, **kwargs):
            starts.append(clock[0])
            return io.BytesIO(b'{"ok":true}')

        def sleep(seconds):
            clock[0] += seconds

        with patch.object(fetch.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(fetch.time, "sleep", side_effect=sleep), \
             patch.object(fetch.urllib.request, "urlopen", side_effect=open_url):
            first = fetch.get_bytes("https://example.invalid/one", self.cache)
            fetch.get_bytes("https://example.invalid/two", self.cache)
            self.assertEqual(fetch.get_bytes("https://example.invalid/one", self.cache), first)
        self.assertEqual(starts, [100.0, 101.0])

    def test_throttling_stops_without_retry_or_cache(self):
        error = HTTPError("https://example.invalid", 429, "throttled", {}, None)
        with patch.object(fetch.urllib.request, "urlopen", side_effect=error) as request:
            with self.assertRaisesRegex(SystemExit, "stopped without retrying"):
                fetch.get_bytes("https://example.invalid", self.cache)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(list(self.cache.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
