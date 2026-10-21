#!/usr/bin/python3
"""Reserve ephemeral serverless fixture listeners inside the lane port range.

Only abbagate/gate_quiet/gates_test self-test entry points use this adapter.
Production servers, clients, assertions, timing limits and return codes are unchanged.
"""
import errno
import os
from pathlib import Path
import runpy
import socket
import sys

entry, *arguments = sys.argv[1:]
original_bind = socket.socket.bind

def bind(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address[1] == 0:
        for port in range(25880, 25900):
            fixed = (address[0], port, *address[2:])
            try:
                result = original_bind(sock, fixed)
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    continue
                raise
            with open('/home/user/Projects/cx-notifyorder/docs/notifyorder/fixture-ports.log', 'a') as log:
                log.write(f'{os.getpid()} {entry} {fixed!r}\n')
            return result
        raise OSError(errno.EADDRINUSE, 'notifyorder fixture port range exhausted')
    return original_bind(sock, address)

socket.socket.bind = bind
sys.argv = [entry, *arguments]
sys.path[0] = str(Path(entry).resolve().parent)
runpy.run_path(entry, run_name='__main__')
