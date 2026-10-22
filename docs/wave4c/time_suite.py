#!/usr/bin/env python3
"""Time unchanged gate suites/tests; optional cProfile for the exhaustive argv test."""
import atexit
import cProfile
import json
import os
from pathlib import Path
import pstats
import runpy
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ['WAVE4C_TIMINGS'])
OUT.mkdir(parents=True, exist_ok=True)
suite = Path(sys.argv[1]).stem
started = time.monotonic()
rows = []
original = unittest.TestCase.run


def timed(self, result=None):
    begin = time.monotonic()
    profile = cProfile.Profile() if (os.getenv('WAVE4C_PROFILE') == '1' and
        self._testMethodName == 'test_dry_run_matches_real_boot_argv_for_every_cell_and_both_arms') else None
    try:
        if profile:
            profile.enable()
        return original(self, result)
    finally:
        if profile:
            profile.disable()
            with (OUT / (suite + '.profile.txt')).open('w') as stream:
                pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(70)
        rows.append(dict(test=self.id(), seconds=time.monotonic() - begin))


def finish():
    (OUT / (suite + '.json')).write_text(json.dumps(dict(
        argv=sys.argv, seconds=time.monotonic() - started,
        cpus=sorted(os.sched_getaffinity(0)), tests=rows), indent=2) + '\n')


unittest.TestCase.run = timed
atexit.register(finish)
sys.argv = sys.argv[1:]
sys.path.insert(0, str(ROOT / 'tests'))
runpy.run_path(sys.argv[0], run_name='__main__')
