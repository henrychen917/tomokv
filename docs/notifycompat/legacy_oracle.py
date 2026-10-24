#!/usr/bin/env python3
"""Exact oracle evidence for the changed historical notify.py assertions."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from notifycompat import Peer

p = argparse.ArgumentParser()
p.add_argument('host')
p.add_argument('port', type=int)
p.add_argument('--case')
a = p.parse_args()
peer = Peer(a.host, a.port)
try:
    peer.setup()
    peer.configure('KEg')
    peer.step('notify.py elapsed SET generic event', ('SET', 'str:past', 'v', 'PXAT', '1'),
              b'OK', [('expire', 'str:past')])
    for command in (
        ('BITOP', 'AND', 'store:bit', 'none:a', 'none:z'),
        ('SINTERSTORE', 'store:set', 'none:a', 'none:z'),
        ('SUNIONSTORE', 'store:sunion:empty', 'none:a', 'none:z'),
        ('SDIFFSTORE', 'store:sdiff:empty', 'none:a', 'none:z'),
        ('ZRANGESTORE', 'store:z', 'none:z', '0', '-1'),
        ('SORT', 'none:sort', 'STORE', 'store:sort:empty'),
    ):
        peer.step('notify.py absent destination', command, 0, [])
    assert not peer.failures, peer.failures
    print('PASS historical assertions vs Redis 7.4')
finally:
    peer.close()
