"""Confine serverless self-tests ephemeral loopback listeners to this lane."""
import errno
import socket
_original_bind = socket.socket.bind

def _lane_bind(sock, address):
    if (sock.family == socket.AF_INET and isinstance(address, tuple) and
            address[0] in ("127.0.0.1", "localhost", "") and address[1] == 0):
        for port in range(23880, 23900):
            try:
                return _original_bind(sock, (address[0], port))
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise
        raise OSError(errno.EADDRINUSE, "moverfix self-test port pool exhausted")
    return _original_bind(sock, address)
socket.socket.bind = _lane_bind
