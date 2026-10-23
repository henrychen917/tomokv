"""Retain gate-owned plans, ledgers, paired replies and job logs, excluding binaries."""
from pathlib import Path
import json,re,tarfile,sys
root=Path(__file__).resolve().parents[2]
out=root/'docs/datafix1'
for name in sys.argv[1:]:
    log=out/(name+'-gate.log');text=log.read_text()
    assert 'GATE(PARTIAL):' in text or 'LANE INTERRUPTED:' in text,(name,'still running')
    run=Path(re.search(r'artifacts: (.*)',text)[1])
    with tarfile.open(out/(name+'-proof.tar.gz'),'w:gz') as archive:
        for path in sorted(run.rglob('*')):
            if not path.is_file() or path.is_symlink():continue
            # GCC's temporaries and captured native snapshots are not proof receipts.
            if path.suffix in ('.o','.s','.so','.a','.tomo','.rdb','.aof'):continue
            with path.open('rb') as f:head=f.read(4)
            if head==b'\x7fELF':continue
            archive.add(path,arcname=str(path.relative_to(run)),recursive=False)
    print(name,re.search(r'(?:GATE\(PARTIAL\):|LANE INTERRUPTED:).*',text)[0],flush=True)
