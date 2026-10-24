#!/usr/bin/env python3
"""SV4.8 PFSELFTEST, including an oracle-backed broken-estimator control."""
from _serverfix import main, Server
from _serverfix_mutant import zero_hll_count


def probe(run, mode, label, extra):
    for limit in [3000, 0]:
        with Server(run, label + '-normal-' + str(limit), mode,
                    extra=extra + ['--hll-sparse-max-bytes', str(limit)]) as server, server.client() as c:
            c.sock.settimeout(30)
            run.check(label + ' sentinel', c.cmd('SET', 'hll-selftest-sentinel', 'unchanged'), b'OK')
            run.check(label + ' selftest ' + str(limit), c.cmd('PFSELFTEST'), b'OK')
            run.check(label + ' no dataset side effects', c.cmd('GET', 'hll-selftest-sentinel'), b'unchanged')
            run.check(label + ' no extra keys', c.cmd('DBSIZE'), 1)
    original = run.binary
    mutant = run.path / ('count-zero-' + label)
    run.rows[label + '-fault-control'] = zero_hll_count(original, mutant, run.oracle)
    run.binary = mutant
    try:
        with Server(run, label + '-fault', mode, extra=extra) as server, server.client() as c:
            c.sock.settimeout(30)
            reply = c.cmd('PFSELFTEST')
            run.check(label + ' broken estimator detected', reply,
                      {'error': 'ERR TESTFAILED Too big error. card:10 abserr:10'})
            run.check(label + ' control remains usable', c.cmd('PING'), b'PONG')
    finally:
        run.binary = original
        mutant.unlink()


if __name__ == '__main__':
    raise SystemExit(main(probe))
