#!/usr/bin/env python3
"""Run the unchanged ccfix instruction/unit/layout witnesses on ccfix5 arms."""
import argparse
import resource
import subprocess

import ccfix3_prove as proof

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof', choices=('units', 'instructions', 'layouts', 'debug'))
    args = parser.parse_args()
    proof.OUT = proof.ROOT / 'docs/ccfix5'
    proof.BUILD = proof.ROOT / 'build/ccfix5'
    proof.OUT.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if args.proof == 'debug':
        for arm in ('PRE', 'POST'):
            core = [o for o in proof.objects(arm) if not o.endswith('/main.o')]
            binary = proof.compile_test('debug-' + arm, proof.ROOT / 'tests/ccfix5_debug_unit.cc', core)
            result = subprocess.run(['taskset', '-c', '112-119', str(binary)],
                                    text=True, capture_output=True)
            (proof.OUT / ('debug-' + arm + '.log')).write_text(
                result.stdout + result.stderr + f'exit={result.returncode}\n')
            if arm == 'PRE':
                assert result.returncode != 0 and 'disagrees with MSET routing namespace' in result.stderr
            else:
                assert result.returncode == 0, result.stderr
            print(arm, 'expected failure' if arm == 'PRE' else 'PASS', flush=True)
    else:
        getattr(proof, args.proof)()
