#!/usr/bin/env python3
"""Stale-copy negative control and forward regeneration of ordinary accounting."""
from pathlib import Path
import tempfile

import r7shadow_sync as sync
import source_tokens as cpp


def main():
    root = sync.ROOT
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp)
        for name in ('io_loop.h', 'ex_loop.h', 'genthread.cc', 'reorder.cc'):
            path = target / 'src/core' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text((root / 'src/core' / name).read_text())
        # clientcompat lets owners publish TRACKING acknowledgements during
        # LB's IoDrain. The armed copy must retain that same progress rule;
        # otherwise the pending acknowledgement can prevent the drain itself.
        copied = target / 'src/core/reorder.cc'
        original_copy = cpp.read(copied)
        freeze = 'const bool lb_frozen = lb_controller_armed_ && srv_->lb_stage() == LbStage::ExDrain;'
        assert original_copy.count(freeze) == 1
        copied.write_text(original_copy.replace(freeze,
            'const bool lb_frozen = lb_controller_armed_ && srv_->lb_dispatch_paused();', 1))
        sync.ROOT = target
        try:
            bodies, _ = sync.envelopes()
            try:
                sync.base.update(copied, bodies, False)
            except ValueError as error:
                assert 'stale R7 envelope' in str(error)
            else:
                raise AssertionError('stale tracking/LB freeze negative control passed')
            sync.base.update(copied, bodies, True)
            assert cpp.tokens(cpp.read(copied)) == cpp.tokens(original_copy)
        finally:
            sync.ROOT = root
        io = target / 'src/core/io_loop.h'
        original = cpp.read(io)
        needle = 'self_->sample_depth(pass_ns / 1000)'
        assert needle in original, 'accounting mutation must edit a real sample site'
        # This is a generator input, not a C++ build: exercise the spelling that
        # the old generator explicitly prohibited in an ordinary envelope.
        io.write_text(original.replace(needle, 'self_->sample_depth(busy.start_ns() / 1000)', 1))
        sync.ROOT = target
        try:
            bodies, declarations = sync.envelopes()
            assert bodies.count('fused_executor_->fused_owner_turn<true>()') == 2
            assert 'fused_executor_->fused_owner_turn()' not in bodies
            assert 'self_->sample_depth(busy.start_ns() / 1000)' in bodies
            path = target / 'src/core/reorder.cc'
            try:
                sync.base.update(path, bodies, False)
            except ValueError as error:
                assert 'stale R7 envelope' in str(error)
            else:
                raise AssertionError('stale-envelope negative control passed')
            sync.base.update(path, bodies, True)
            sync.base.update(path, bodies, False)
            for owner, name in (('ExLoopT<Fused>', 'ex_loop.h'), ('IoLoop', 'io_loop.h')):
                generated = ''.join('    ' + line + '\n' for line in declarations[owner].splitlines())
                sync.base.update(target / 'src/core' / name, generated, True)
                sync.base.update(target / 'src/core' / name, generated, False)
        finally:
            sync.ROOT = root
    print('PASS stale R7 envelope rejected; tracking/LB freeze and accounting regenerate and check')


if __name__ == '__main__':
    main()
