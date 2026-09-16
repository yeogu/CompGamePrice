"""Atomic, job-local progress reporting; disabled outside an administrator job."""

import json
import os
from pathlib import Path
import tempfile
import threading


class ProgressReporter:
    def __init__(self, total):
        destination = os.getenv("GAME_PRICE_COLLECTION_PROGRESS_PATH")
        self.path = Path(destination) if destination else None
        self.lock = threading.Lock()
        self.state = {"total": total, "processed": 0, "succeeded": 0, "failed": 0}
        self._publish()

    def completed(self, succeeded):
        with self.lock:
            self.state["processed"] += 1
            self.state["succeeded" if succeeded else "failed"] += 1
            self._publish()

    def _publish(self):
        if self.path is None:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(self.state, output)
            os.replace(temporary, self.path)
        except OSError:
            # Reporting must never turn a successful collection into a failure.
            if temporary is not None:
                temporary.unlink(missing_ok=True)
