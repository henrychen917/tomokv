#!/usr/bin/env python3
"""Serverless witness for the real LB episode's exceptional cleanup ordering.

--negative-control restores the old cleanup edges in a throwaway run_episode;
the witness MUST fail. No server, socket or load process is started by this test.
"""
from contextlib import ExitStack, contextmanager, redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("connreset_lb_episodes", ROOT / "tools/lb_episodes.py")
episodes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(episodes)


class HarnessCleanup(unittest.TestCase):
    def episode(self, baseline_fail=True, observer_error=None):
        events, samplers = [], []
        with tempfile.TemporaryDirectory(prefix=".connreset-", dir=ROOT / "tests") as tmp:
            args = episodes.argument_parser().parse_args(["--output", tmp])
            identity = {"shards": 64, "process_id": 123}
            seed = {"shards": 64, "sha256": "test seed", "hot_keys": []}

            class Thread:
                running = False

                def start(self):
                    self.running = True
                    events.append("sampler-start")

                def join(self):
                    self.running = False
                    events.append("sampler-joined")

                def is_alive(self):
                    return self.running

            def sampler(*args):
                instance = real_sampler(*args)
                instance.thread = Thread()
                instance.error = observer_error
                # Bench5 also validates captured owner maps after a good baseline.
                instance.samples = [{"t": 0, "signals": {"shards": {
                    sid: {"owner": 0} for sid in range(identity["shards"])}}}]
                samplers.append(instance)
                return instance

            @contextmanager
            def boot(*args):
                children = SimpleNamespace(start=lambda *args: events.append("loader-start"))
                try:
                    yield None, children, list(range(8)), identity
                finally:
                    events.append("server-stop")
                    if samplers and samplers[0].thread.running:
                        # Model the actual failure: shutdown while polling sets
                        # the sampler error; its late close used to mask baseline.
                        samplers[0].error = "[Errno 104] Connection reset by peer"

            real_sampler = episodes.Sampler
            baseline = {"status": "FAIL" if baseline_fail else "PASS",
                        "reason": "balanced total_moves=1, limit=0 (key=0, client=1)"}
            with ExitStack() as mocks, redirect_stdout(io.StringIO()):
                for name, replacement in {
                    "boot": boot, "Sampler": sampler, "key_mapping": lambda *a: [],
                    "load_command": lambda *a, **k: ["memtier-test-double"],
                    "wait_loads": lambda *a: 1, "owner_evidence": lambda *a: {},
                    "baseline_stationarity": lambda *a: baseline,
                    "envelope": lambda *a: {"test": True},
                }.items():
                    mocks.enter_context(patch.object(episodes, name, replacement))
                result = episodes.run_episode(args, "PRE", "2s", "balanced", 1,
                                              Path(tmp) / "seed", seed)
            return result, events, samplers[0]

    def test_baseline_failure_joins_monitor_before_server_and_preserves_cause(self):
        result, events, sampler = self.episode()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], "balanced total_moves=1, limit=0 (key=0, client=1)")
        self.assertIsNone(sampler.error)
        self.assertLess(events.index("sampler-joined"), events.index("server-stop"))
        self.assertEqual(events.count("sampler-joined"), 1)
        self.assertEqual(events.count("loader-start"), 2)

    def test_real_monitor_failure_still_fails_successful_episode(self):
        result, events, _ = self.episode(False, "real established-connection reset")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("real established-connection reset", result["reason"])
        self.assertLess(events.index("sampler-joined"), events.index("server-stop"))

    def test_two_failures_keep_original_and_record_observer_failure(self):
        result, _, _ = self.episode(True, "independent monitor error")
        self.assertIn("balanced total_moves=1", result["reason"])
        self.assertEqual(result["sampler_error"], "sampler failed: independent monitor error")
        self.assertFalse(result["measurement_valid"])

    def test_success_joins_once_before_server(self):
        result, events, _ = self.episode(False)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(events.count("sampler-joined"), 1)
        self.assertLess(events.index("sampler-joined"), events.index("server-stop"))


def install_negative_control():
    """Restore just the two bad cleanup edges in a throwaway function object."""
    import inspect
    source = inspect.getsource(episodes.run_episode)
    context = "            with sampled_episode(sampler, result):\n"
    handler = "    except Exception as error:\n"
    finalizer = "    finally:\n"
    for marker in (context, handler, finalizer):
        if source.count(marker) != 1:
            raise RuntimeError("negative control cannot identify unique cleanup edge: " + marker.strip())
    prefix, body = source.split(context)
    body, suffix = body.split(handler)
    # Remove only the inner sampled_episode lifetime. Its body still runs under
    # boot, but now an exception escapes to server teardown before sampler close.
    body = "".join(line[4:] if line.strip() else line
                   for line in body.splitlines(keepends=True))
    # The old happy path already closed the sampler inside boot; only its
    # exceptional edge escaped that close and then overwrote the first failure.
    source = (prefix + "            sampler.thread.start()\n" + body
              + "            sampler.close()\n" + handler + suffix)
    source = source.replace(finalizer, finalizer + '''        if sampler:
            try:
                sampler.close()
            except Exception as error:
                result.update(status="FAIL", reason=str(error), measurement_valid=False)
''')
    exec(compile(source, "<connreset-old-cleanup-control>", "exec"), episodes.__dict__)


if __name__ == "__main__":
    if "--negative-control" in sys.argv:
        sys.argv.remove("--negative-control")
        install_negative_control()
    unittest.main()
