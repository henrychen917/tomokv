#!/usr/bin/env python3
"""Finite production command scopes for rootcompat, on the lane's CPUs only."""
import sys
from pathlib import Path
import flipfix5_counts as counts

root = Path(__file__).resolve().parents[1]
counts.BUILD = root / 'build/rootcompat/counts'
counts.OUT = root / 'docs/rootcompat/counts'
counts.PRE_COMMIT = '7d2f8a2051961a1942735fb6dc9b507d778e09d1'
counts.CPUS = '48-63'
counts.ARMS = {
    'pre': (root / 'build/rootcompat/pre-source', root / 'build/rootcompat/pre-source/build'),
    'post': (root, root / 'build'),
}
if __name__ == '__main__':
    if '--probes' not in sys.argv:
        sys.argv += ['--probes', 'command']
    counts.main()
