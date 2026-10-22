#!/usr/bin/env python3
"""Run one tests/differ.py leg with every write to the TARGET fragmented (NT4.2).

Same argv as tests/differ.py. Oracle writes are untouched, so the oracle sees the
unsplit stream and every differ comparison (byte or property) is between a
fragmented target and an unfragmented Redis 7.4. Each target sendall is cut at
seeded random positions (about one per 32 bytes, 1..64 per write); pieces are
separated by a short pause so the target's reads observe partial frames
(including frames that end mid-next-frame in pipelined batches). The cut stream
is a pure function of (suite, seed).
"""
import random
import runpy
import socket
import sys
import time
from pathlib import Path

GAP_SECONDS = 0.0002
argv = sys.argv[1:]
target = (argv[0], int(argv[1]))
suite = argv[4]
seed = next((arg for arg in argv[5:] if arg != '-3'), '7')
rng = random.Random(f'respresume-frag:{suite}:{seed}')
original_sendall = socket.socket.sendall
stats = dict(writes=0, pieces=0)


def fragmented_sendall(self, data, *flags):
    try:
        peer = self.getpeername()
    except OSError:
        peer = None
    data = bytes(data)
    if peer is None or (peer[0], peer[1]) != target or len(data) < 2:
        return original_sendall(self, data, *flags)
    # About one cut per 32 bytes (at least 1, at most 64 per write): in pipelined batches most
    # frames are split, and many cuts land inside the next frame's header or payload.
    count = min(len(data) - 1, 64, max(1, len(data) // 32))
    cuts = sorted(rng.sample(range(1, len(data)), count))
    previous = 0
    for cut in cuts + [len(data)]:
        original_sendall(self, data[previous:cut], *flags)
        stats['pieces'] += 1
        previous = cut
        if cut != len(data):
            time.sleep(GAP_SECONDS)
    stats['writes'] += 1
    return None


socket.socket.sendall = fragmented_sendall
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
sys.argv = [str(here / 'differ.py')] + argv
try:
    runpy.run_path(str(here / 'differ.py'), run_name='__main__')
finally:
    print(f"FRAGMENTED target writes={stats['writes']} pieces={stats['pieces']}", file=sys.stderr)
