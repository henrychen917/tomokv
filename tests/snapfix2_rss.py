#!/usr/bin/env python3
"""RSS correctness with a large, fixed live set and periodic BGSAVEs (no rate verdict).

Use snapfix.py's boot/matrix CLI: --case large-rss --dataset 1000000. Sixteen saves;
touch existing keys between saves, check exact cardinality and verify the final snapshot reload.
"""
import json
import time

import snapfix as s


def case_large_rss(args, directory, mode, engine, atomic, oracle):
    with s.Boot(args, directory, mode, engine, atomic, oracle) as b:
        c = b.c
        s.populate(c, args.dataset)
        assert c.must('DBSIZE') == args.dataset, 'large dataset never loaded'
        completed_before = int(s.persistence(c)['rdb_saves'])
        rss, starts, seconds = [], [], []
        for n in range(16):
            # Cardinality stays fixed; these values must survive the final snapshot.
            for i in range(32):
                assert c.must('SET', f'snapfix:fill:{i}', str(n)) == b'OK'
            time.sleep(.05)
            began = time.monotonic()
            assert c.must('BGSAVE') == b'Background saving started'
            starts.append(time.monotonic() - began)
            s.bgsave_done(c, args.stall)
            completed = int(s.persistence(c)['rdb_saves']) - completed_before
            assert completed == n + 1, ('BGSAVE never completed its cut', n + 1, completed)
            seconds.append(time.monotonic() - began)
            rss.append(s.stats(c, 'memory')['used_memory_rss'])
            assert c.must('DBSIZE') == args.dataset
        result = dict(keys=args.dataset, rss=rss, start_seconds=starts, seconds=seconds,
                      completed_saves=completed)
        (directory / 'rss.json').write_text(json.dumps(result, indent=2) + '\n')
        assert max(rss[2:]) <= 3 * rss[1] + (64 << 20), ('large BGSAVE loop grew', result)
    with s.Boot(args, directory, mode, engine, atomic, oracle, (), 'restart') as b:
        assert b.c.must('DBSIZE') == args.dataset
        keys = [f'snapfix:fill:{i}' for i in range(32)]
        assert b.c.must('MGET', *keys) == [b'15'] * 32, 'snapshot lost final replacements'
        assert b.c.must('GET', f'snapfix:fill:{args.dataset - 1}') == b'v' * 16
    return result


if __name__ == '__main__':
    s.CASES = {'large-rss': case_large_rss}
    raise SystemExit(s.main())
