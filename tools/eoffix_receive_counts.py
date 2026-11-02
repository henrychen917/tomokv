#!/usr/bin/env python3
"""Count the ordinary epoll event plus short receive in production bodies."""
import argparse
import os
from pathlib import Path
import eoffix_counts
from wave14_counts import census, trace, save, sha

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('arm', choices=['pre', 'post'])
a = p.parse_args()
assert os.sched_getaffinity(0) <= set(range(8))
source = ROOT/'build/eoffix/pre-source' if a.arm == 'pre' else ROOT
label = a.arm+'-receive'
rows = []
for ns in ('normal', 'db0'):
    binary = census.build(label, source, source/'build', ns, 'tests/eoffix_receive_scope.cc')
    prepared = census.prepare(binary, source/'build', ns, 'lua')
    for command, mode in (('EPOLL', '1s'), ('EPOLL', '2s'), ('EPOLL-R7', '1s')):
        for batch in (1, 32):
            rows.append(trace(prepared, label, ns, (command, mode, batch, 0, 0)))
save(census.DOC/label/'counts.json', dict(server_sha256=sha(source/'build/tomokv'), rows=rows))
