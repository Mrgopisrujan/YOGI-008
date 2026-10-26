"""Flight Data Recorder — jsonl per-flight recorder.

Best-effort: never blocks control loop >1ms. Logs preflight + grants + all topics.
Default format: jsonl (KD25). MCAP optional later.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .topics import TOPICS


class FdrRecorder:
    """JSONL flight data recorder.

    Usage:
        fdr = FdrRecorder(Path("flight_logs/flight_001.jsonl"))
        fdr.record("arbiter_grant", {"mode": "hover", "v_max": 0.0})
        fdr.close()
    """

    def __init__(self, path: Path, buffer_flush_interval_s: float = 0.1) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8")
        self._buffer: list[str] = []
        self._last_flush = time.monotonic()
        self._flush_interval = buffer_flush_interval_s
        self._closed = False

    def record(self, topic: str, data: dict[str, Any]) -> None:
        """Record a data point. Non-blocking (buffered)."""
        if self._closed:
            return

        entry = {
            "ts": time.time(),
            "topic": topic,
            "data": data,
        }
        self._buffer.append(json.dumps(entry, default=str))
        self._maybe_flush()

    def record_preflight(self, preflight: dict[str, Any]) -> None:
        """Record preflight snapshot."""
        self.record("preflight", preflight)

    def flush(self) -> None:
        """Force flush buffer to disk."""
        if self._buffer:
            self._file.write("\n".join(self._buffer) + "\n")
            self._file.flush()
            self._buffer.clear()
        self._last_flush = time.monotonic()

    def close(self) -> None:
        """Flush and close the recorder."""
        self.flush()
        self._file.close()
        self._closed = True

    def _maybe_flush(self) -> None:
        """Flush if buffer is large enough or enough time has passed."""
        now = time.monotonic()
        if len(self._buffer) >= 100 or (now - self._last_flush) >= self._flush_interval:
            self.flush()

    def __enter__(self) -> "FdrRecorder":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
