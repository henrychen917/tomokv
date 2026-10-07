"""Bounded CLIENT LIST witnesses for gate-owned connections."""
import time

from _lib import call


def wait_client_state(observer, client_id, state, timeout=5.0):
    """Require this exact client to be blocked or gone; never infer it from a sleep."""
    if state not in ("blocked", "gone"):
        raise ValueError("client state must be blocked or gone")
    client_id = str(client_id)
    if not client_id.isdecimal():
        raise ValueError("client ID must be a decimal integer")
    deadline = time.monotonic() + timeout
    original = observer.sock.gettimeout()
    last = None
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise AssertionError("client %s never became %s: %r" % (client_id, state, last))
            observer.sock.settimeout(left if original is None else min(left, original))
            last = call(observer, "CLIENT", "LIST", "ID", client_id)
            if isinstance(last, bytes):
                last = last.decode()
            if not isinstance(last, str):
                raise AssertionError("CLIENT LIST did not return text: %r" % (last,))
            rows = last.splitlines()
            if len(rows) > 1:
                raise AssertionError("CLIENT LIST ID returned multiple clients: %r" % last)
            fields = dict(item.split("=", 1) for item in rows[0].split()) if rows else {}
            if fields and (fields.get("id") != client_id or "flags" not in fields):
                raise AssertionError("CLIENT LIST ID returned malformed witness: %r" % last)
            left = deadline - time.monotonic()
            if left <= 0:
                raise AssertionError("client %s observation exceeded deadline: %r" % (client_id, last))
            if (state == "gone" and not rows) or (state == "blocked" and "b" in fields.get("flags", "")):
                return
            time.sleep(min(.005, left))
    finally:
        observer.sock.settimeout(original)
