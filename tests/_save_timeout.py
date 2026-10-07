"""Client-side SAVE budgets; these do not change server coordination deadlines."""
from contextlib import contextmanager


def save_timeout_seconds(value_bytes):
    if value_bytes < 0:
        raise ValueError('save size must be nonnegative')
    # Fixed setup allowance plus a conservative 8 MiB/s serialization/IO budget.
    return 30.0 + value_bytes / (8 * 1024 * 1024)


@contextmanager
def save_reply_timeout(sock, value_bytes):
    original = sock.gettimeout()
    sock.settimeout(max(original or 0, save_timeout_seconds(value_bytes)))
    try:
        yield
    finally:
        sock.settimeout(original)
