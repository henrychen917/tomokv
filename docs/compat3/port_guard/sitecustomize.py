"""Keep disposable Python socket fixtures inside this lane's allocated ports.

Enabled only by verify.py's PYTHONPATH and COMPAT3_PORT_RECEIPT. Target and
oracle services already receive explicit gate ports. No protocol, comparison,
deadline or verdict code is changed; only bind(..., 0) port selection changes.
"""
import json
import os
import socket

receipt = os.environ.get("COMPAT3_PORT_RECEIPT")
if receipt:
    original_bind = socket.socket.bind

    def lane_bind(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return original_bind(sock, address)
        host, port, *rest = address
        if port:
            if not 25800 <= port <= 25899:
                raise AssertionError(f"compat3 listener outside allocated range: {address!r}")
            return original_bind(sock, address)
        # All fixtures are private loopback listeners. Exclude the directed
        # inventory's 25890/25891 and gate self-test's explicitly assigned 25899.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        last_error = None
        for candidate in range(25892, 25899):
            chosen = (host, candidate, *rest)
            try:
                result = original_bind(sock, chosen)
            except OSError as error:
                if error.errno != 98:  # EADDRINUSE: try the next reserved port.
                    raise
                last_error = error
                continue
            event = dict(pid=os.getpid(), requested=list(address), bound=list(chosen))
            with open(receipt, "a") as output:
                output.write(json.dumps(event) + "\n")
            return result
        raise last_error

    socket.socket.bind = lane_bind
