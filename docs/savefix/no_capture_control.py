#!/usr/bin/env python3
"""Independent AOF/undecided-EXEC shutdown control; deliberately starts no capture."""
import argparse
import json
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
import savefix

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--port', type=int, required=True)
p.add_argument('--cores', required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--attempts', type=int, default=16)
a = p.parse_args()
a.case, a.mode, a.atomic, a.net_io = 'rewrite', '1s', 0, 'epoll'
a.ratio, a.keys, a.value_bytes = '6:2', 131072, 200
a.databases, a.read_local, a.aof, a.oracle = 1, 0, True, False
a.output.mkdir(parents=True, exist_ok=False)
for n in range(a.attempts):
    directory = a.output / ('attempt-%d' % (n + 1))
    directory.mkdir()
    with savefix.boot(a, directory, 'write') as (process, conn, log):
        savefix.seed(a, conn)
        writers = savefix.Writers(a)
        writers.start()
        state = savefix.info(conn, 'persistence')
        assert int(state['rdb_bgsave_in_progress']) == 0
        assert int(state['aof_rewrite_in_progress']) == 0
        savefix.emit('stop_without_any_snapshot', acked=writers.acked[:], load=savefix.load())
        process.send_signal(signal.SIGTERM)
        try:
            assert process.wait(timeout=15) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            writers.finish()
        (directory / 'result.json').write_text(json.dumps(
            dict(status=process.returncode, load=savefix.load(), snapshot_started=False)) + '\n')
