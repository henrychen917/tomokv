#!/usr/bin/env python3
"""Hold allocated TCP ports against ephemeral autobind without listening.

Linux SO_REUSEADDR allows the real server/control listener to bind over this
non-listening socket. The gate still owns each actual listener and its PID.
No host sysctl, protocol, assertion or deadline is changed. Stop with SIGTERM.
"""
import argparse
import errno
import json
import os
import signal
import socket
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--ports', nargs='+', type=int, default=[40840, 40841, 40842])
p.add_argument('--receipt', default='docs/lualibs/port-reservations.jsonl')
a = p.parse_args()
assert all(40800 <= port <= 40899 for port in a.ports)
held = {}
stopping = False

def stop(*_):
    global stopping
    stopping = True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    while not stopping:
        for port in a.ports:
            if port in held:
                continue
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('127.0.0.1', port))
            except OSError as error:
                sock.close()
                if error.errno != errno.EADDRINUSE:
                    raise
                continue  # A real listener or earlier client still owns it.
            held[port] = sock
            event = dict(pid=os.getpid(), port=port, time=time.time(), listening=False)
            with open(a.receipt, 'a') as out:
                out.write(json.dumps(event) + '\n')
            print(json.dumps(event), flush=True)
        time.sleep(0.1 if len(held) != len(a.ports) else 1)
finally:
    for sock in held.values():
        sock.close()
