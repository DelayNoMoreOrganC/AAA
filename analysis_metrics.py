"""Per-call monotonic timing, without case identifiers or document contents."""
from contextlib import contextmanager
from time import perf_counter


class AnalysisMetrics:
    def __init__(self, log):
        self.values = {"scope": "this_analysis_call"}
        self.log = log

    @contextmanager
    def measure(self, stage):
        if stage not in ("analysis", "source_ingest", "field_agent"):
            raise ValueError("Unknown analysis timing stage")
        started = perf_counter()
        success = False
        try:
            yield
            success = True
        finally:
            elapsed = round(max(0.0, perf_counter() - started), 3)
            self.values[stage + "_seconds"] = elapsed
            self.values[stage + "_status"] = "completed" if success else "failed"
            try:
                self.log(f"[性能] {stage}: {elapsed:.3f}s; status={self.values[stage + '_status']}")
            except Exception:
                # Diagnostics cannot replace the operation's result or error.
                pass

    def call(self, stage, function, *args, **kwargs):
        with self.measure(stage):
            return function(*args, **kwargs)
