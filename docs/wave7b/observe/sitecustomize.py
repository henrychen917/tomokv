"""Timing-only observer; selected by PYTHONPATH in the wave7b job receipt."""
import atexit
import json
import os
from pathlib import Path
import sys
import time

out = os.getenv("WAVE7B_TIMINGS")
if out and (Path(sys.argv[0]).name in {"gates_test.py", "gate_process_test.py", "gate_subset_test.py", "background_environment_test.py"} or
            any(arg in {"--self-test", "self-test"} for arg in sys.argv[1:])):
    import unittest
    started = time.monotonic()
    rows = []
    original = unittest.TestCase.run
    def timed(self, *args, **kwargs):
        begin = time.monotonic()
        try:
            return original(self, *args, **kwargs)
        finally:
            rows.append(dict(test=self.id(), seconds=time.monotonic()-begin))
    unittest.TestCase.run = timed
    setup = unittest.TestSuite._handleClassSetUp
    def observed_setup(self, test, result):
        cls = type(test)
        if cls.__name__ == "SchedulerWiring" and not getattr(cls, "wave7b_observed", False):
            cls.wave7b_observed = True
            prepare = cls.prepare_fixture
            def fixture(self, options):
                begin = time.monotonic()
                try:
                    return prepare(self, options)
                finally:
                    rows.append(dict(fixture=options, seconds=time.monotonic()-begin))
            cls.prepare_fixture = fixture
        return setup(self, test, result)
    unittest.TestSuite._handleClassSetUp = observed_setup
    def save():
        if rows:
            path = Path(out); path.mkdir(parents=True, exist_ok=True)
            (path / (Path(sys.argv[0]).stem + "-" + str(os.getpid()) + ".json")).write_text(
                json.dumps(dict(argv=sys.argv, affinity=sorted(os.sched_getaffinity(0)),
                                seconds=time.monotonic()-started, tests=rows), indent=2, default=str)+"\n")
    atexit.register(save)
