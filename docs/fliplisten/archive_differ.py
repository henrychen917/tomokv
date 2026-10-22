"""Keep completed differential text receipts, excluding generated server data."""
import hashlib
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for name in sys.argv[1:]:
    assert name in {e + '-' + g for e in ('uring', 'epoll')
                    for g in ('split', 'armed-fused')}
    dest = ROOT / 'docs/fliplisten/differ' / name
    result = json.loads((dest / 'result.json').read_text())
    source = ROOT / 'build/fliplisten/differ' / (name + '-results')
    files = sorted(p for p in source.rglob('*') if p.is_file()
                   and p.suffix in ('.json', '.txt', '.log'))
    assert files
    archive = dest / 'receipts.tar.gz'
    with tarfile.open(archive, 'w:gz') as out:
        for path in files:
            out.add(path, arcname=str(path.relative_to(source)), recursive=False)
    manifest = dict(result=result, files=len(files),
                    source=str(source.relative_to(ROOT)),
                    sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    (dest / 'receipts.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(name, manifest)
