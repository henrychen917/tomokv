import ast
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, 'tests')
mode, host, port = sys.argv[1:]
sys.argv = ['atomic_torn', host, port]
source = Path('tests/atomic_torn.py')
body = []
for node in ast.parse(source.read_text()).body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'geometry' for t in node.targets):
        break
    body.append(node)
ns = {'__name__': 'gt14fix2_controls'}
exec(compile(ast.Module(body=body, type_ignores=[]), str(source), 'exec'), ns)
Resp, config = ns['Resp'], ns['config']
keys = ns['gate_geometry']()['mover_pair']
if mode == 'no-hold':
    result = ns['rename_held'](0, keys)
    print('no-hold result:', result, flush=True)
    assert result[1] == 0 and result[2] and 'not witnessed' in result[2][0]
    print('PASS absent hold is rejected')
    sys.exit()

def held(atomic, budget, pause, expire=False):
    config('atomic', atomic)
    admin, writer = Resp(), Resp()
    replies, errors = [], []
    admin.cmd('DEL', *keys)
    admin.cmd('SET', keys[0], 'rename-value')
    assert admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-HOLD', str(budget)) == b'OK'
    assert admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-STATUS') == 1
    started = time.monotonic()
    def rename():
        try:
            replies.append(writer.cmd('RENAME', *keys))
        except Exception as e:
            errors.append(str(e))
    worker = threading.Thread(target=rename)
    worker.start()
    try:
        deadline = started + 5
        status = 1
        while status == 1 and time.monotonic() < deadline:
            status = admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-STATUS')
            time.sleep(.001)
        assert status == 2, (status, replies, errors)
        time.sleep(pause)
        status = admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-STATUS')
        if expire:
            assert status == 3, status
            worker.join(timeout=5)
            assert replies == [b'OK'] and not errors, (replies, errors)
            # Completion does not reset an expired latch, and a subsequent RENAME cannot claim it.
            assert admin.cmd('RENAME', keys[1], keys[0]) == b'OK'
            assert admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-STATUS') == 3
        else:
            expected = [b'rename-value', None] if atomic else [None, None]
            assert status == 2 and not replies and not errors, (status, replies, errors)
            assert admin.cmd('MGET', *keys) == expected
            assert admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-STATUS') == 2
        print('PASS', dict(atomic=atomic, budget_ms=budget, elapsed_s=time.monotonic()-started, status=status), flush=True)
    finally:
        assert admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-HOLD', '0') == b'OK'
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert admin.cmd('DEBUG', 'ATOMIC-OFF-HOP-STATUS') == 0
        admin.close()
        writer.close()
    assert replies == [b'OK'] and not errors

for atomic in (0, 1):
    held(atomic, 30000, 1.2)
held(0, 100, .2, expire=True)
# The uint64 maximum must be clamped before multiplication; a 30 s wait proves the hard cap.
if mode == 'cap':
    held(0, 2**64 - 1, 30.1, expire=True)
print('PASS hold controls')
