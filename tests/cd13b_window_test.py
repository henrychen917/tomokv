#!/usr/bin/env python3
"""The real GEO property must rearm moved placement and reject a never-open window."""
import contextlib
import io
import unittest
from unittest.mock import patch

from cd13b_wire import geo_store_property


def bulk(value):
    value = str(value).encode()
    return b'$%d\r\n' % len(value) + value + b'\r\n'


class Fixture:
    def __init__(self, never_opens=False, prime_moves=1, store_moves=0,
                 never_stable=False, migration_only=False, same_owner_after=False,
                 corrupt=None, cold=False, expire_after_store=False):
        self.never_opens = never_opens
        self.prime_moves = prime_moves
        self.store_moves = store_moves
        self.never_stable = never_stable
        self.migration_only = migration_only
        self.same_owner_after = same_owner_after
        self.corrupt = corrupt
        self.cold = cold
        self.expire_after_store = expire_after_store
        self.clock = 0
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
            self.frequency.pop(args[1], None)
            return b':0\r\n'
        if command == 'GEOADD':
            self.sources.append(args[1])
            self.clock += 1
            return b':2\r\n'
        if command == 'ZADD':
            self.frequency.setdefault(args[1], 5)
            return b':1\r\n' if len(args) == 4 else b':159\r\n'
        if command == 'ZREM':
            return b':158\r\n'
        if command == 'ZCARD':
            self.frequency[args[1]] = 5 if self.cold else 9
            return b':2\r\n'
        if command == 'OBJECT':
            broken = args[2] in self.stored and ':0:source' in args[2]
            if args[1] == 'FREQ':
                if broken and self.corrupt == 'freq-type':
                    return bulk('9')
                if broken and self.corrupt == 'freq-reset':
                    return b':5\r\n'
                return b':%d\r\n' % self.frequency[args[2]]
            if broken and self.corrupt == 'encoding':
                return bulk('skiplist')
            return bulk('listpack' if args[2] in self.stored else 'skiplist')
        if command == 'ZRANGE':
            if self.corrupt == 'members' and ':0:source' in args[1]:
                return b'*2\r\n' + bulk('a') + bulk('wrong')
            return b'*2\r\n' + bulk('a') + bulk('b')
        if command in ('GEORADIUS', 'GEOSEARCHSTORE'):
            destination = args[1] if command == 'GEOSEARCHSTORE' else args[-1]
            self.stores.append(destination)
            self.stored.add(destination)
            if self.expire_after_store:
                self.clock += 30
            if self.corrupt == 'count' and ':0:source' in destination:
                return b':1\r\n'
            return b':2\r\n'
        raise AssertionError(args)

    def route(self, keys):
        pair = tuple(keys)
        count = self.routes.get(pair, 0) + 1
        self.routes[pair] = count
        # Selection sees two owners. Priming closes the first attempt's window;
        # a new key pair is required before a stable cross-owner STORE is possible.
        attempt = int(keys[0].split(':')[-2])
        if count >= 2 and (self.never_opens or attempt < self.prime_moves):
            return ((0, 0, 0), (1, 0, 1))
        if count >= 3 and (self.never_stable or attempt < self.store_moves):
            owner = 0 if self.migration_only else (1 if self.same_owner_after else 6)
            return ((0, owner, 2), (1, 1, 0))
        return ((0, 0, 0), (1, 1, 0))


class PlacementWindow(unittest.TestCase):
    def check(self, fixture):
        log = io.StringIO()
        with contextlib.redirect_stdout(log), patch('cd13b_wire.time.monotonic', lambda: fixture.clock):
            failures = geo_store_property([('target', fixture.call)], fixture.route)
        self.assertEqual(fixture.stored, set())
        self.assertEqual(fixture.frequency, {})
        self.assertEqual(fixture.settings, {'maxmemory': b'0', 'maxmemory-policy': b'noeviction'})
        return failures, log.getvalue()

    def test_migration_while_priming_rearms_on_fresh_keys(self):
        fixture = Fixture()
        failures, log = self.check(fixture)
        self.assertEqual(failures, 0, log)
        self.assertEqual(len(fixture.stores), 3)
        self.assertEqual(len(fixture.sources), 6)
        self.assertEqual(log.count('CD13b GEO rearm'), 3)

    def test_window_that_never_opens_fails_at_deadline(self):
        fixture = Fixture(never_opens=True)
        failures, log = self.check(fixture)
        self.assertEqual(failures, 3, log)
        self.assertEqual(fixture.stores, [])
        self.assertEqual(len(fixture.sources), 90)
        self.assertIn('window budget', log)

    def test_more_than_three_invalid_arms_can_establish_a_witness(self):
        fixture = Fixture(prime_moves=4)
        failures, log = self.check(fixture)
        self.assertEqual(failures, 0, log)
        self.assertEqual(len(fixture.stores), 3)
        self.assertEqual(len(fixture.sources), 15)

    def test_source_moves_during_store_require_fresh_stable_cross_owner_arm(self):
        for options in ({}, {'same_owner_after': True}, {'migration_only': True}):
            with self.subTest(options=options):
                fixture = Fixture(prime_moves=0, store_moves=4, **options)
                failures, log = self.check(fixture)
                self.assertEqual(failures, 0, log)
                self.assertEqual(len(fixture.stores), 15)
                self.assertEqual(len(set(fixture.stores)), 15)
                self.assertEqual(log.count('route moved during STORE'), 12)
                self.assertEqual(log.count("members=[b'a', b'b']"), 15)

    def test_perpetual_post_store_migration_never_passes(self):
        fixture = Fixture(prime_moves=0, never_stable=True)
        failures, log = self.check(fixture)
        self.assertEqual(failures, 3, log)
        self.assertEqual(len(fixture.stores), 87)
        self.assertIn('window budget', log)

    def test_cold_lfu_never_passes(self):
        fixture = Fixture(prime_moves=0, cold=True)
        failures, log = self.check(fixture)
        self.assertEqual(failures, 3, log)
        self.assertEqual(fixture.stores, [])

    def test_bad_store_is_never_retried_even_when_route_moved(self):
        for corrupt in ('count', 'freq-type', 'freq-reset', 'encoding', 'members'):
            for moved in (False, True):
                with self.subTest(corrupt=corrupt, moved=moved):
                    fixture = Fixture(prime_moves=0, store_moves=int(moved), corrupt=corrupt)
                    failures, log = self.check(fixture)
                    self.assertEqual(failures, 3, log)
                    # Later arms would be healthy. A retry would conceal the defect.
                    self.assertEqual(len(fixture.stores), 3)
                    self.assertEqual(len(fixture.sources), 3)
                    self.assertNotIn('route moved during STORE', log)

    def test_deadline_cannot_accept_an_otherwise_valid_store(self):
        fixture = Fixture(prime_moves=0, expire_after_store=True)
        failures, log = self.check(fixture)
        self.assertEqual(failures, 3, log)
        self.assertEqual(len(fixture.stores), 3)
        self.assertEqual(log.count('STORE checks exhausted window budget'), 3)


if __name__ == '__main__':
    unittest.main()
