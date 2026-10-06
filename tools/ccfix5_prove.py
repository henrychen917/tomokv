#!/usr/bin/env python3
"""Run the unchanged ccfix instruction/unit/layout witnesses on ccfix5 arms."""
import argparse
import resource

import ccfix3_prove as proof

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof', choices=('units', 'instructions', 'layouts'))
    args = parser.parse_args()
    proof.OUT = proof.ROOT / 'docs/ccfix5'
    proof.BUILD = proof.ROOT / 'build/ccfix5'
    proof.OUT.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    getattr(proof, args.proof)()
