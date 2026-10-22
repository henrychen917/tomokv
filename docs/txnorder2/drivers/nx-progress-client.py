#!/usr/bin/env python3
"""The exact NX data checks, with progress after completed barrier generations."""
from pathlib import Path
import sys
import threading

root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'tests'))
import txn_nx
progress=Path(sys.argv.pop())
barrier=threading.Barrier
created=0
def witnessed_barrier(parties,action=None,timeout=None):
    global created
    created+=1
    if created%2==0:
        completed=[0]
        def after():
            completed[0]+=1
            if completed[0]%64==0:progress.write_text(str(completed[0]))
            if action:action()
        return barrier(parties,action=after,timeout=timeout)
    return barrier(parties,action=action,timeout=timeout)
threading.Barrier=witnessed_barrier
raise SystemExit(txn_nx.main())
