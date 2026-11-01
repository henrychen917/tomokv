#!/usr/bin/env python3
"""FUNCTION rewrite-capture/journal interaction; a required forced window per leg."""
import argparse
import contextlib
import copy
import os
from pathlib import Path
import time
from _lib import Conn
from persistfix2 import boot, emit, wait, rewrite_done

SOURCE = "#!lua name=wave14\nredis.register_function('wave14',function() return %d end)"

def probe(a):
    opts = ['--appendonly', 'yes', '--appendfsync', a.fsync, '--databases', str(a.databases)]
    hold = a.output/'capture-hold'
    os.environ['WAVE14_CAPTURE_HOLD'] = str(hold)
    with boot(a, 'write', opts) as (_, c, data), contextlib.ExitStack() as stack:
        assert c.must('FUNCTION', 'LOAD', SOURCE % 1) == b'wave14'
        assert c.must('SET', 'wave14:key', 'before') == b'OK'
        if a.oracle:
            control = c
        else:
            # The AOF writer is the final IO (or final fused thread). A FUNCTION
            # on a separate IO is allowed while that writer holds the capture.
            control = None
            for _ in range(128):
                candidate = stack.enter_context(contextlib.closing(Conn('127.0.0.1', a.port, timeout=15)))
                if candidate.must('DEBUG', 'IO-THREAD') == 0:
                    control = candidate
                    break
            assert control is not None, 'no IO-0 controller'
            hold.touch(exist_ok=False)
        try:
            assert control.must('BGREWRITEAOF').startswith(b'Background append only file rewriting')
            if not a.oracle:
                wait(lambda: Path(str(hold)+'.ready').exists(), 'library image copied before mutation')
            assert control.must('FUNCTION', 'LOAD', 'REPLACE', SOURCE % 2) == b'wave14'
            assert b'return 2' in control.must('FUNCTION', 'LIST', 'WITHCODE')[0][-1]
            emit('risky moment', case='FUNCTION replaced after rewrite library capture',
                 hits=1, scheduled=not a.oracle, fsync=a.fsync)
        finally:
            hold.unlink(missing_ok=True)
        wait(lambda: rewrite_done(control), 'rewrite completed')
        assert control.must('SET', 'wave14:key', 'after') == b'OK'
        assert control.must('FCALL', 'wave14', 0) == 2
    with boot(a, 'restart', opts, existing_data=data) as (_, c, _):
        assert c.must('GET', 'wave14:key') == b'after'
        result = c.must('FCALL', 'wave14', 0)
        assert result == 2, ('rewrite discarded post-capture FUNCTION journal', result)
    os.environ.pop('WAVE14_CAPTURE_HOLD', None)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--oracle', type=Path, required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--single', action='store_true')
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=True)
    legs = [(True, 'oracle', 'normal', 1, policy) for policy in ('always','everysec','no')]
    legs += [(False, mode, engine, db, policy) for mode in ('1s','2s')
             for engine in ('uring','epoll') for db in (1,16) for policy in ('always','everysec','no')]
    if a.single: legs = [(False, '2s', 'epoll', 16, 'no')]
    failures = []
    for oracle, mode, engine, db, policy in legs:
        leg = copy.copy(a)
        leg.oracle, leg.mode, leg.engine, leg.databases, leg.fsync = oracle, mode, engine, db, policy
        leg.output = a.output/f'{mode}-{engine}-db{db}-{policy}'
        leg.output.mkdir()
        if oracle: leg.binary = a.oracle
        try:
            probe(leg); emit('pass', leg=leg.output.name)
        except Exception as error:
            failures.append((leg.output.name, repr(error)))
            emit('FAIL', leg=leg.output.name, error=repr(error))
    assert not failures, failures

if __name__ == '__main__': main()
