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
        # Supply the required policy inventory so this control reaches the
        # missing command check instead of failing the earlier policy check.
        names = (
            'tomo::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()',
            'tomo::ExLoopT<true>::fused_sweep_impl<32u, true, false, true>()',
            'tomo::ExLoopT<true>::fused_baseline_sweep()',
            'tomo::ExLoopT<true>::run()',
            'tomo::IoLoop::run_loop<false, false, true, false, false, false>()',
            'tomo::IoLoop::flush_ready<false, false, true, false, false, true>()',
            'tomo::cmd_get(X)',
        )
        pre = SimpleNamespace(groups={name: [dict(
            addr=16 * (index + 1), size=1, ins=['ret'], encodings=['c3'], aliases=[name])]
            for index, name in enumerate(names)})
        assert all(row['equal'] for row in audit.compare(pre, pre, Path(tmp)))
        post = SimpleNamespace(groups=dict(pre.groups))
        del post.groups['tomo::cmd_get(X)']
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
