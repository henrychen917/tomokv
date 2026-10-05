#!/usr/bin/env python3
"""Compile throwaway missing-fence controls and require their directed witness to fail."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import iopass_receipts as receipts

CONTROLS = {
    'flip-no-sample': (
        'src/core/io_loop.h',
        'void flip_pass_begin() { flip_stage_snapshot_ = srv_->flip_stage(); }',
        'void flip_pass_begin() { flip_stage_snapshot_ = FlipStage::Idle; }',
        'next pass ACKs the armed drain'),
    'flip-open-parser': (
        'src/core/io_loop.h',
        'const bool flip_pause_this_pass = flip_dispatch_paused();',
        'const bool flip_pause_this_pass = false;',
        'post-ACK sweep/parser cannot publish'),
    'flip-stale-tail': (
        'src/core/io_loop.h',
        'const FlipStage stage = srv_->flip_stage();\n        if (flip_stage_snapshot_',
        'const FlipStage stage = flip_stage_snapshot_;\n        if (flip_stage_snapshot_',
        'armed control tail does not ACK an old sampled stage'),
    'flip-cached-coordinator': (
        'src/core/io_loop.h',
        'c == flip_client_ && srv_->flip_dispatch_paused()',
        'c == flip_client_ && flip_pause_this_pass',
        'coordinator uses immediate live fence'),
}


def control(name, source):
    out = receipts.ROOT / 'build/iopass-receipts' / name / 'source'
    shutil.copytree(source / 'src', out / 'src', dirs_exist_ok=True)
    filename, before, after, failure = CONTROLS[name]
    path = out / filename
    text = path.read_text()
    assert text.count(before) == 1, (name, 'mutation must fire exactly once')
    path.write_text(text.replace(before, after))
    binary = receipts.build(name, out, checks=True)
    result = subprocess.run(['taskset', '-c', '112-127', str(binary), 'checks'],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode != 0 and failure in result.stdout + result.stderr, (
        name, 'must fail its directed assertion, not build/crash/skip', result)
    print('PASS negative control', name, 'rejected:', result.stderr.strip(), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=CONTROLS)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    control(args.name, args.source.resolve())
