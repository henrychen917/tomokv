#!/usr/bin/env python3
"""Gate candidate adapter: supply a default engine/mode to unchanged gate jobs.

Explicit per-job choices win. The actual release ELF is exec'd, with its PID and
all protocol traffic still owned by tests/gate.sh and its usual batteries.
"""
import json
import os
from pathlib import Path
import sys

binary = os.environ['IOFIX_BINARY']
args = sys.argv[1:]
if args and args[0] in ('--version', '-v', '--help', '-h'):
    os.execv(str(Path(binary).resolve()), [str(Path(binary).resolve()), *args])
defaults = []
if os.environ.get('IOFIX_FORCE_ENGINE') == '1':
    if '--net-io' in args:
        args[args.index('--net-io') + 1] = os.environ['IOFIX_ENGINE']
    args = ['--net-io=' + os.environ['IOFIX_ENGINE'] if x.startswith('--net-io=') else x
            for x in args]
if not any(x == '--net-io' or x.startswith('--net-io=') for x in args):
    defaults += ['--net-io', os.environ.get('IOFIX_ENGINE', 'uring')]
if os.environ.get('IOFIX_MODE') == '1s' and not any(
        x == '--thread-mode' or x.startswith('--thread-mode=') for x in args):
    if '--ratio' in args:
        i = args.index('--ratio')
        del args[i:i + 2]
    args = [x for x in args if not x.startswith('--ratio=')]
    defaults += ['--thread-mode', '1s']
# A config file must remain argv[1]. Subsequent options override it as usual.
offset = int(bool(args and not args[0].startswith('-')))
args[offset:offset] = defaults
command = [str(Path(binary).resolve()), *args]
if os.environ.get('IOFIX_LAUNCH_LOG'):
    # Error-injection batteries inherit a small RLIMIT_FSIZE. A cumulative log can exceed
    # that limit before exec, preventing the intended server failure from ever being tested.
    # One short file per launch retains argv without changing the injected resource limit.
    directory = Path(os.environ['IOFIX_LAUNCH_LOG'] + '.d')
    directory.mkdir(exist_ok=True)
    (directory / (str(os.getpid()) + '.json')).write_text(
        json.dumps(dict(pid=os.getpid(), argv=command)) + '\n')
os.execv(command[0], command)
