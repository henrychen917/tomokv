"""CG4.1 diagnostic: fresh config-user credentials, full bytes versus NUL prefix.

This is an open baseline failure, not a passing compatibility row.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path('tests').resolve()))
from authfix import Server, clean, Resp

os.environ['LC_ALL'] = 'C'
root = Path('build/witnessfix/userline-v2').resolve()
root.mkdir(parents=True, exist_ok=False)
rows = []
for role, binary in [('oracle', '/home/user/Projects/redis/src/redis-server'),
                     ('candidate', str(Path('build/witnessfix/tomokv-7d2f8a205').resolve()))]:
    for mode in (['2s'] if role == 'oracle' else ['1s', '2s']):
        path = root / (role + '-' + mode)
        path.mkdir()
        conf = path / 'fixture.conf'
        conf.write_text('user witness on ">foo\\x00tail" ~* +@all\n')
        run = SimpleNamespace(path=path, binary=Path(binary), oracle=role == 'oracle',
                              args=SimpleNamespace(port=20577, cores='80-87', ratio='6:2', databases=16))
        with Server(run, 'server', mode, conf=conf) as process:
            with Resp(20577) as client: full = client.cmd('AUTH', 'witness', b'foo\x00tail')
            with Resp(20577) as client: prefix = client.cmd('AUTH', 'witness', b'foo')
        rows.append(dict(root='CG4.1 USER-LINE-NUL', role=role, mode=mode,
                         full=clean(full), prefix=clean(prefix)))
        print(rows[-1], flush=True)
        if role == 'oracle':
            assert full == b'OK' and isinstance(prefix, dict), rows[-1]
Path('docs/witnessfix/userline-results.json').write_text(json.dumps(rows, indent=2) + '\n')
assert all(r['full'] == 'OK' and isinstance(r['prefix'], dict) for r in rows), 'CG4.1 config-user password is truncated'
