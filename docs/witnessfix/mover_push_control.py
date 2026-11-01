"""Compile the real mover fixture with stale phase-one selection reinstated."""
from pathlib import Path
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path('tools').resolve()))
from aclkeys3_controls import command
root = Path.cwd()
folder = root / 'build/witnessfix/mover-push-control'
folder.mkdir(parents=True, exist_ok=True)
shutil.copytree(root / 'src', folder / 'src', dirs_exist_ok=True)
p = folder / 'src/cmd/xshard_movers.inc'
original = p.read_text()
old = 'moved = xshard_peek_list(shard.store().find(key.hash, op.arg(key.arg)),\n                                              state.from_left, element);'
assert original.count(old) == 1
changed = original.replace(old, 'moved = XshardElementResult::Ok; // planted stale phase-one element')
p.write_text(changed)
Path('docs/witnessfix/mover-stale-selection.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True), fromfile='src/cmd/xshard_movers.inc', tofile='planted/src/cmd/xshard_movers.inc')))
rows = []
for suffix in ('', '-db0'):
    target = Path('build/moverfix' + suffix + '-unit')
    cmd = command(target, 'tests/moverfix_unit.cc')
    cmd.insert(1, '-I' + str(folder))
    binary = folder / target.name
    cmd[cmd.index('-o') + 1] = str(binary)
    with (folder/(target.name + '-build.log')).open('w') as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    for mode in ('1s', '2s'):
        result = subprocess.run([str(binary), mode, 'PUSH'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        row = dict(database_image='db0' if suffix else 'db16', mode=mode, command=cmd, exit=result.returncode, stdout=result.stdout,
                   sha256=hashlib.file_digest(binary.open('rb'), 'sha256').hexdigest())
        rows.append(row)
        Path('docs/witnessfix/mover-stale-selection.json').write_text(json.dumps(rows, indent=2)+'\n')
        assert result.returncode != 0 and 'nonempty source must yield two distinct claims' in result.stdout, row
        print(mode, suffix or 'db16', 'negative control failed at distinct-claim conservation', flush=True)
