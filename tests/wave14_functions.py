#!/usr/bin/env python3
"""FUNCTION rewrite-capture/journal interaction; a required forced window per leg.

PS5.3: every registry mutation (LOAD REPLACE, a new LOAD, DELETE, RESTORE and FLUSH)
lands while BGREWRITEAOF holds its copied library image, in both modes, both engines
and every appendfsync policy, and must survive restart replay.
"""
import argparse
import contextlib
import copy
import os
from pathlib import Path
import time
import traceback
from _lib import Conn
from persistfix2 import boot, emit, wait, rewrite_done

SOURCE = "#!lua name=wave14\nredis.register_function('wave14',function() return %d end)"
EXTRA = "#!lua name=wave14b\nredis.register_function('wave14b',function() return 7 end)"
KINDS = ('replace', 'load', 'delete', 'restore', 'flush')


def registry_empty(c):
    return c.must('FUNCTION', 'LIST') == []


def mutation(kind, c):
    """Arm one mutation on this server; returns (argv, reply, state check)."""
    if kind == 'replace':
        return (['FUNCTION', 'LOAD', 'REPLACE', SOURCE % 2], b'wave14',
                lambda x: x.must('FCALL', 'wave14', 0) == 2)
    if kind == 'load':
        return (['FUNCTION', 'LOAD', EXTRA], b'wave14b',
                lambda x: x.must('FCALL', 'wave14b', 0) == 7 and x.must('FCALL', 'wave14', 0) == 1)
    if kind == 'delete':
        return (['FUNCTION', 'DELETE', 'wave14'], b'OK', registry_empty)
    if kind == 'restore':
        # This server's own frame for {wave14 v3}. Arming mutations precede the rewrite.
        assert c.must('FUNCTION', 'LOAD', 'REPLACE', SOURCE % 3) == b'wave14'
        payload = c.must('FUNCTION', 'DUMP')
        assert c.must('FUNCTION', 'LOAD', 'REPLACE', SOURCE % 1) == b'wave14'
        assert c.must('FCALL', 'wave14', 0) == 1
        return (['FUNCTION', 'RESTORE', payload, 'REPLACE'], b'OK',
                lambda x: x.must('FCALL', 'wave14', 0) == 3)
    assert kind == 'flush'
    return (['FUNCTION', 'FLUSH'], b'OK', registry_empty)


def probe(a):
    opts = ['--appendonly', 'yes', '--appendfsync', a.fsync, '--databases', str(a.databases)]
    hold = a.output/'capture-hold'
    os.environ['WAVE14_CAPTURE_HOLD'] = str(hold)
    with boot(a, 'write', opts) as (_, c, data), contextlib.ExitStack() as stack:
        assert c.must('FUNCTION', 'LOAD', SOURCE % 1) == b'wave14'
        assert c.must('SET', 'wave14:key', 'before') == b'OK'
        argv, reply, check = mutation(a.kind, c)
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
            control.send(*argv)
            # always/everysec hold this IO's sends behind the writer. The
            # test-only journal wrapper proves enqueueing in the held window
            # without requiring a reply through that same send gate.
            if a.oracle:
                assert control.read() == reply
            else:
                wait(lambda: Path(str(hold)+'.journal').exists(),
                     'mutation journal enqueued while capture is held')
            emit('risky moment', case='FUNCTION ' + a.kind + ' after rewrite library capture',
                 hits=1, scheduled=not a.oracle, fsync=a.fsync)
        finally:
            hold.unlink(missing_ok=True)
        if not a.oracle:
            assert control.read() == reply
        assert check(control), ('live registry does not show the mutation', a.kind)
        wait(lambda: rewrite_done(control), 'rewrite completed')
        assert control.must('SET', 'wave14:key', 'after') == b'OK'
    with boot(a, 'restart', opts, existing_data=data) as (_, c, _):
        assert c.must('GET', 'wave14:key') == b'after'
        state = c.must('FUNCTION', 'LIST', 'WITHCODE')
        assert check(c), ('rewrite discarded post-capture FUNCTION journal', a.kind, state)
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
    policies = ('always', 'everysec', 'no')
    # The original LOAD REPLACE matrix keeps both namespaces; the other kinds cover
    # PS5.3's specification: both modes, both engines and every fsync policy.
    legs = [(True, 'oracle', 'normal', 1, policy, kind) for kind in KINDS for policy in policies]
    legs += [(False, mode, engine, db, policy, 'replace') for mode in ('1s','2s')
             for engine in ('uring','epoll') for db in (1,16) for policy in policies]
    legs += [(False, mode, engine, 16, policy, kind) for kind in KINDS[1:] for mode in ('1s','2s')
             for engine in ('uring','epoll') for policy in policies]
    if a.single: legs = [(False, '2s', 'epoll', 16, 'no', 'replace')]
    failures = []
    for oracle, mode, engine, db, policy, kind in legs:
        leg = copy.copy(a)
        leg.oracle, leg.mode, leg.engine, leg.databases, leg.fsync, leg.kind = oracle, mode, engine, db, policy, kind
        suffix = '' if kind == 'replace' else '-' + kind
        leg.output = a.output/f'{mode}-{engine}-db{db}-{policy}{suffix}'
        leg.output.mkdir()
        if oracle: leg.binary = a.oracle
        try:
            probe(leg); emit('pass', leg=leg.output.name)
        except Exception as error:
            traceback.print_exc()
            failures.append((leg.output.name, repr(error)))
            emit('FAIL', leg=leg.output.name, error=repr(error))
    assert not failures, failures

if __name__ == '__main__': main()
