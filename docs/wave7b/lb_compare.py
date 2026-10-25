#!/usr/bin/env python3
"""Unchanged natural-skew test, with already-read LB counters retained."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import perfio
p = argparse.ArgumentParser()
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--port', type=int, default=26850)
p.add_argument('--cores', default='64-71')
a = p.parse_args()
a.mode='2s'; a.net_io='epoll'; a.ratio='6:2'; a.oracle=False
old = perfio.info
last = [0.]
def observed(*args):
    row = old(*args)
    if args[1:] == ('LB',) and time.monotonic() - last[0] > 1:
        perfio.emit(event='lb-counters', counters=row)
        last[0] = time.monotonic()
    return row
perfio.info=observed
perfio.epoll_lb(a)
