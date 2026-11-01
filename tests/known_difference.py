"""Exact, named deviations are visible exclusions from Redis compatibility evidence."""


def expect(got, redis, *, root, known):
    if got == redis:
        return True
    assert got == known, (root, 'unrecognized difference', got, 'Redis', redis)
    print(f'KNOWN DIFFERENCE {root}: Redis={redis!r}; observed={got!r}; '
          'excluded from compatibility evidence', flush=True)
    return False
