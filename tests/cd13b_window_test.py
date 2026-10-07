#!/usr/bin/env python3
"""The real GEO property must rearm moved placement and reject a never-open window."""
import contextlib
import io
import unittest

from cd13b_wire import geo_store_property


def bulk(value):
    value = str(value).encode()
    return b'$%d\r\n' % len(value) + value + b'\r\n'


class Fixture:
    def __init__(self, never_opens=False):
        self.never_opens = never_opens
        self.settings = {'maxmemory': '0', 'maxmemory-policy': 'noeviction'}
        self.frequency = {}
        self.stored = set()
        self.sources = []
        self.stores = []
        self.routes = {}

    def call(self, args):
        command = args[0]
        if command == 'CONFIG':
            if args[1] == 'GET':
                return b'*2\r\n' + bulk(args[2]) + bulk(self.settings[args[2]])
            self.settings[args[2]] = args[3]
            return b'+OK\r\n'
        if command == 'DEL':
            self.stored.discard(args[1])
            return b':0\r\n'
        if command == 'GEOADD':
            self.sources.append(args[1])
            return b':2\r\n'
        if command == 'ZADD':
            self.frequency.setdefault(args[1], 5)
            return b':1\r\n' if len(args) == 4 else b':159\r\n'
        if command == 'ZREM':
            return b':158\r\n'
        if command == 'ZCARD':
            self.frequency[args[1]] = 9
            return b':2\r\n'
        if command == 'OBJECT':
            if args[1] == 'FREQ':
                return b':%d\r\n' % self.frequency[args[2]]
            return bulk('listpack' if args[2] in self.stored else 'skiplist')
        if command in ('GEORADIUS', 'GEOSEARCHSTORE'):
            destination = args[1] if command == 'GEOSEARCHSTORE' else args[-1]
            self.stores.append(destination)
            self.stored.add(destination)
            return b':2\r\n'
        raise AssertionError(args)

    def route(self, keys):
        pair = tuple(keys)
        count = self.routes.get(pair, 0) + 1
        self.routes[pair] = count
        # Selection sees two owners. Priming closes the first attempt's window;
        # a new key pair is required before a stable cross-owner STORE is possible.
        moved = count >= 2 and (self.never_opens or ':0:source' in keys[0])
        return ((0, 0, 0), (1, 0, 1) if moved else (1, 1, 0))


class PlacementWindow(unittest.TestCase):
    def check(self, fixture):
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            failures = geo_store_property([('target', fixture.call)], fixture.route)
        return failures, log.getvalue()

    def test_migration_while_priming_rearms_on_fresh_keys(self):
        fixture = Fixture()
        failures, log = self.check(fixture)
        self.assertEqual(failures, 0, log)
        self.assertEqual(len(fixture.stores), 3)
        self.assertEqual(len(fixture.sources), 6)
        self.assertEqual(log.count('CD13b GEO rearm'), 3)

    def test_window_that_never_opens_fails_after_three_fresh_attempts(self):
        fixture = Fixture(never_opens=True)
        failures, log = self.check(fixture)
        self.assertEqual(failures, 3, log)
        self.assertEqual(fixture.stores, [])
        self.assertEqual(len(fixture.sources), 9)
        self.assertEqual(log.count('window never armed on three fresh destinations'), 3)


if __name__ == '__main__':
    unittest.main()
