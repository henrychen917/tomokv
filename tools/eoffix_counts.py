#!/usr/bin/env python3
"""Reuse wave14's serverless instruction instrument with eoffix source arms."""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import wave14_counts as counts

ROOT = Path(__file__).resolve().parents[1]
counts.BUILD = ROOT/'build/eoffix'
counts.DOC = ROOT/'docs/eoffix'
counts.PRE = ROOT/'build/eoffix/pre-source'
counts.census.BUILD = counts.BUILD/'counts'
counts.census.DOC = counts.DOC/'instructions'

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('arm', choices=['pre', 'post'])
    p.add_argument('--kind', choices=['ordinary', 'parser'], required=True)
    p.add_argument('--only', default='GET,SET,INCR,MGET,MSET')
    p.add_argument('--tag', default='')
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(8))
    source = counts.PRE if a.arm == 'pre' else ROOT
    label = a.arm+'-'+a.kind+('-'+a.tag if a.tag else '')
    fixture = 'tests/wave14_parser_scope.cc' if a.kind == 'parser' else 'tests/blockfix4_scope.cc'
    rows = []
    for ns in ('normal', 'db0'):
        binary = counts.census.build(label, source, source/'build', ns, fixture)
        prepared = counts.census.prepare(binary, source/'build', ns, 'lua')
        # The pre-existing parser fixture covers read-local GET. MGET's armed
        # cut fence admits one frame per owner drain, outside that fixture's
        # single parser-call contract; its requested ordinary receive scope is
        # therefore explicitly read-local=0, in both arms.
        cases = [(c, mode, batch, atomic, local) for c in a.only.split(',')
                 for mode in ('1s', '2s') for batch in (1, 32)
                 for atomic in ((1,) if a.kind == 'parser' else (0, 1))
                 for local in ((0, 1) if a.kind == 'parser' and mode == '1s' and
                               c in ('PARSE-GET', 'PARSE-SET', 'PARSE-INCR') else
                               ((0,) if a.kind == 'parser' else (-1,)))]
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows.extend(pool.map(lambda c: counts.trace(prepared, label, ns, c), cases))
    counts.save(counts.census.DOC/label/'counts.json', dict(
        server_sha256=counts.sha(source/'build/tomokv'), rows=rows))
