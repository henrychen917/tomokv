"""Keep Python fixture listeners inside fliplisten's authorized ports.

This affects listener allocation only, including child Python interpreters.
Assertions, deadlines and production server arguments are unchanged.
"""
import errno
import os
import socket

_bind = socket.socket.bind


def bind(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
        if address[1] == 0:
            for port in range(21880, 21899):
                try:
                    result = _bind(sock, (address[0], port, *address[2:]))
                except OSError as error:
                    if error.errno == errno.EADDRINUSE:
                        continue
                    raise
                with open(os.environ['FLIPLISTEN_FIXTURE_PORT_LOG'], 'a') as stream:
                    stream.write(f'{os.getpid()} {port}\n')
                return result
            raise OSError(errno.EADDRINUSE, 'fliplisten fixture ports exhausted')
        if not 21800 <= address[1] <= 21899:
            raise OSError(errno.EACCES, f'listener outside fliplisten allocation: {address!r}')
    return _bind(sock, address)


socket.socket.bind = bind
