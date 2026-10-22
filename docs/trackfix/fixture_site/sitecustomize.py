"""Confine Python test listeners, including bind(0) controls, to lane ports."""
import errno
import os
import socket

_bind = socket.socket.bind


def bind(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
        if address[1] == 0:
            for port in range(22880, 22899):
                try:
                    result = _bind(sock, (address[0], port, *address[2:]))
                except OSError as error:
                    if error.errno == errno.EADDRINUSE:
                        continue
                    raise
                with open(os.environ['TRACKFIX_FIXTURE_PORT_LOG'], 'a') as stream:
                    stream.write(f'{os.getpid()} {port}\n')
                return result
            raise OSError(errno.EADDRINUSE, 'trackfix fixture ports exhausted')
        if not 22800 <= address[1] <= 22899:
            raise OSError(errno.EACCES, f'listener outside trackfix allocation: {address!r}')
    return _bind(sock, address)


socket.socket.bind = bind
