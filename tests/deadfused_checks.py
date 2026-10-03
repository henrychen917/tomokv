#!/usr/bin/env python3
"""Serverless replay and fail-closed audit controls for the deadfused cleanup."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

import read_local_lane as lane
import reorder_noop as audit


def main():
    for trace in ('transient', 'delayed-drain', 'mget-fence'):
        lane.self_test(trace)
    for trace, message in (
            ('mget-fence-old', 'RL1: N MGET lane hits before ROB retirement'),
            ('mget-fence-unarmed', 'MGET fence window never opened after 3 fresh arms'),
            ('mget-fence-stale', 'MGET pipeline replies/order/RYOW')):
        try:
            lane.self_test(trace)
        except AssertionError as error:
            assert str(error).startswith(message), (trace, str(error))
            print('PASS expected rejection:', trace)
        else:
            raise AssertionError('accepted negative control: ' + trace)
    for key in lane.REMOVED_KEYS:
        try:
            lane.assert_retired_keys_absent({key: '0'})
        except AssertionError as error:
            assert 'retired INFO key' in str(error)
        else:
            raise AssertionError('accepted zero retired key: ' + key)
    print('PASS all retired INFO keys reject zero-valued rows')
    scratch = Path(__file__).resolve().parents[1] / 'build' / 'deadfused'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        pre = SimpleNamespace(groups={'tomo::cmd_get(X)': [dict(
            addr=16, size=1, ins=['ret'], encodings=['c3'], aliases=['tomo::cmd_get(X)'])]})
        post = SimpleNamespace(groups={})
        try:
            audit.compare(pre, post, Path(tmp))
        except ValueError as error:
            assert 'missing POST symbols' in str(error)
            print('PASS missing-symbol negative control:', error)
        else:
            raise AssertionError('accepted missing POST symbol')
    audit.self_test()


if __name__ == '__main__':
    main()
