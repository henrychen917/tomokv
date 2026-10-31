#!/usr/bin/env python3
"""Command breadth, paired Redis/TomoKV ABBA. See survey-plan.md for workload semantics."""
import sys
from types import SimpleNamespace

import survey as s


def cells(args):
    result = s.command_cells(args)
    if args.smoke:
        # One workload per family; the sidecar still samples the complete catalogue.
        chosen = ('GET', 'HGETALL', 'LRANGE100', 'SMEMBERS', 'ZRANGE', 'XREADGROUP', 'BITCOUNT', 'GEOSEARCH')
        result = [c for c in result if c['workload']['name'] in chosen and
                  c['pipeline'] == (32 if c['family'] in ('hashes', 'sets', 'bitmap_hll', 'geo') else 1) and
                  (c['workload']['name'] not in ('HGETALL', 'SMEMBERS', 'ZRANGE') or c['workload']['cardinality'] == 100)]
    return result


def selftest():
    s.base_selftest()
    args = SimpleNamespace(families='all', pipelines='1,32', keys=32, connections=4, smoke=False)
    catalogue = cells(args)
    assert len(catalogue) == 86
    assert len({c['name'] for c in catalogue}) == 86
    assert {c['family'] for c in catalogue} == set('strings hashes lists sets zsets streams bitmap_hll geo'.split())
    assert len([c for c in catalogue if c['workload']['cardinality'] == 10000]) == 10
    args.smoke = True
    assert len(cells(args)) == 8
    s.rejects(lambda: s.select('missing', ('strings',)))
    print('survey_cmds selftest: PASS')
    return 0


def main():
    p = s.parser(__doc__, all_variants=True)
    p.add_argument('--families', default='all')
    p.add_argument('--pipelines', default='1,32')
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return s.campaign(args, 'survey_cmds', cells)


if __name__ == '__main__':
    sys.exit(main())
