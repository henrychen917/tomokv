#!/usr/bin/env python3
"""Run unchanged ccfix3 witnesses against the fresh ccfix4 arms on CPUs 112-127."""
import argparse
import resource

import ccfix3_prove as proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proof', choices=('units', 'instructions', 'layouts'))
    args = parser.parse_args()
    proof.OUT = proof.ROOT / 'docs/ccfix4'
    proof.BUILD = proof.ROOT / 'build/ccfix4'
    proof.OUT.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    getattr(proof, args.proof)()
