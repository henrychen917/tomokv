#!/usr/bin/env python3
"""Retain GDB stacks for one bounded at412 diagnostic cell."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
import at412 as a
import at412_diagnostics as d

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', default='build/snapfix/pre/tomokv')
p.add_argument('--oracle', default='/home/user/Projects/redis74/src/redis-server')
p.add_argument('--cores', default='16-23')
p.add_argument('--port', type=int, default=20202)
p.add_argument('--mode', default='1s')
p.add_argument('--engine', default='uring')
p.add_argument('--atomic', type=int, default=1)
p.add_argument('--defect', choices=['XS-SHUT-1', 'SNAP-STORM-1'], required=True)
p.add_argument('--mix', default='scripts,execs,writers')
p.add_argument('--seconds', type=int, default=30)
p.add_argument('--attempts', type=int, default=5)
p.add_argument('--core', type=Path)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
args.debug_stacks = True
if args.core:
    original_popen = a.subprocess.Popen
    def capture_core(argv, *pargs, **kwargs):
        if 'gdb' in argv:
            argv = list(argv)
            at = argv.index('--args')
            argv[at:at] = ['-ex', 'generate-core-file '+str(args.core.resolve())]
        return original_popen(argv, *pargs, **kwargs)
    a.subprocess.Popen = capture_core
os.environ['AT412_STORM_MIX'] = args.mix
for i in range(args.attempts):
    try:
        with a.boot(args, args.output/str(i), args.mode, args.engine, args.atomic) as (c, port):
            keys = a.pair(c, 'stack', False)
            call = a.invocation(c, 'EVAL', keys)
            if args.defect == 'XS-SHUT-1':
                d.shutdown(c, port, keys, call, False)
                time.sleep(2)  # let GDB finish the abort backtrace before boot's finalizer
            else:
                a.storm(c, port, keys, call, False, args.seconds, bgsave=True, refusals=[0])
    except Exception:
        print(traceback.format_exc(), flush=True)
        sys.exit(1)
    print(json.dumps(dict(attempt=i, completed=True)), flush=True)
