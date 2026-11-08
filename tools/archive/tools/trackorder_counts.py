#!/usr/bin/env python3
"""Reuse the production command-scope tracer on trackorder's frozen headline.

No server, listening socket, throughput loop or timing verdict. Both namespaces,
thread modes and atomic settings, GET/SET/INCR/MGET/MSET, batches 1 and 32.
"""
import sys
from pathlib import Path
import flipfix5_counts as counts

root = Path(__file__).resolve().parents[1]
counts.BUILD = root / 'build/trackorder/counts'
counts.OUT = root / 'docs/trackorder/counts'
counts.PRE_COMMIT = 'e32b04a445b056976abb308aa598e356fcbaae74'
counts.CPUS = '0-15'
counts.ARMS = {
    'pre': (root / 'build/trackorder/pre-source', root / 'build/trackorder/pre-source/build'),
    'post': (root, root / 'build'),
}
if __name__ == '__main__':
    if '--probes' not in sys.argv:
        sys.argv += ['--probes', 'command']
    counts.main()
