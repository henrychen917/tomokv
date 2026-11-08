#!/usr/bin/env python3
"""Retire large payloads only from completed, passing private gate jobs."""
import argparse, json, os
from pathlib import Path
import exec1sd as d

def main():
    assert os.sched_getaffinity(0) <= set(range(64, 96))
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    args=parser.parse_args()
    root=args.root.resolve()
    assert root.parent==d.ROOT/'build' and root.name.startswith('gate-run.')
    receipt=d.DOCS/'retired-gate-payloads.json'
    rows=json.loads(receipt.read_text()) if receipt.exists() else []
    added=[]
    for folder in sorted((root/'jobs').iterdir()):
        done=folder/'done';ledger=folder/'ledger'
        if not done.exists() or not ledger.exists():continue
        if done.read_text().split()[0]!='0' or any(line.startswith('FAIL\t') for line in ledger.read_text().splitlines()):continue
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.stat().st_size<=8*1024*1024:continue
            if path.suffix not in ('.tomo','.rdb','.objdump') and path.name!='fifo-twin':continue
            # Commit the content identity before removing the reproducible
            # payload. Logs, ledgers, oracles and every failing job remain.
            row=dict(path=str(path),bytes=path.stat().st_size,sha256=d.sha(path),
                     done_sha256=d.sha(done),ledger_sha256=d.sha(ledger))
            rows.append(row);d.save(receipt,rows)
            path.unlink();added.append(row)
    print('retired',len(added),'files,',sum(r['bytes'] for r in added),'bytes')

if __name__=='__main__':main()
