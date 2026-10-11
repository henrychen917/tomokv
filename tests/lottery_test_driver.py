#!/usr/bin/env python3
"""Run an existing battery with observation-only markers; leave assertions intact."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

from _lib import Conn
from _gate_process import info


def main():
    path = Path(sys.argv[1]).resolve()
    sys.argv = [str(path), *sys.argv[2:]]
    if sys.argv[1:] == ['--list-generators']:
        exec(compile(path.read_text(), str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
        return
    port = int(os.environ['LOTTERY_PORT'])
    family = os.environ['LOTTERY_FAMILY']

    def observe(*command, parse=None):
        # One short-lived observer connection per call: the battery never runs
        # beside an extra idle client the gate does not have (maxclients,
        # CLIENT LIST and connection-count assertions stay exactly as gated).
        conn = Conn('127.0.0.1', port)
        try:
            return parse(conn) if parse else conn.must(*command)
        finally:
            conn.close()

    auto = os.environ.get('LOTTERY_AUTO_TRACE')
    metadata = None
    if auto:
        directory = Path(auto)
        directory.mkdir(parents=True, exist_ok=True)
        base = directory / uuid.uuid4().hex
        before = observe(parse=info)
        metadata = dict(pid=int(before['process_id']), trace=str(base.with_suffix('.trace')),
                        before=before, argv=sys.argv)
        observe('DEBUG', 'LOTTERY', 'ARM', os.environ['LOTTERY_MASK'], metadata['trace'])

    def mark(name):
        observe('DEBUG', 'LOTTERY', 'MARK', name)

    def config_sleep(seconds):
        time.sleep(seconds)
        # A single sample after the battery's existing propagation sleep, with
        # no poll/wait/retry. Failure to observe all owners is a missed attempt.
        if seconds >= .05:
            observe('DEBUG', 'LOTTERY', 'CONFIG')

    source = path.read_text()
    original_hash = hashlib.sha256(source.encode()).hexdigest()
    if family in ('blocking', 'servertail', 'slowlog'):
        source = source.replace('time.sleep(', 'lottery_config_sleep(')
    if family == 'expwide':
        for function, name in [('test_fanout_hook', 'fanout'), ('test_transaction_family', 'exec'),
                               ('test_script_clock', 'script'),
                               ('test_ordinary_expiry_still_works', 'ordinary')]:
            anchor = f'        {function}(conn)'
            if source.count(anchor) != 1:
                raise ValueError(f'changed expiry section anchor: {function}')
            source = source.replace(anchor, f'        lottery_mark("expiry_section_{name}")\n' + anchor)
    if path.name == 'differ.py':
        anchor = '        a = parked["t"] + collect(tt); b = parked["o"] + collect(ot)'
        if source.count(anchor) != 1:
            raise ValueError('changed tracking collector anchor')
        source = source.replace(anchor, '        lottery_mark("tracking_compare_begin")\n' + anchor)
        anchor = '        parked["t"] = parked["o"] = b""'
        if source.count(anchor) != 1:
            raise ValueError('changed tracking result anchor')
        source = source.replace(anchor, anchor + '\n        lottery_mark("tracking_compare_zero" if a == b == b"" else "tracking_compare_data")')
    print(f'LOTTERY battery sha256={original_hash} markers_only=1', flush=True)
    try:
        exec(compile(source, str(path), 'exec'), dict(__name__='__main__', __file__=str(path),
             lottery_mark=mark, lottery_config_sleep=config_sleep))
    finally:
        if metadata is not None:
            metadata['after'] = observe(parse=info)
            metadata['stopped'] = observe('DEBUG', 'LOTTERY', 'STOP') == b'OK'
            base.with_suffix('.json').write_text(json.dumps(metadata, indent=2) + '\n')


if __name__ == '__main__':
    main()
