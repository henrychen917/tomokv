#!/usr/bin/env python3
"""Read-only snapshot of relevant concurrent jobs and observed thread affinities."""
import json
import os
from pathlib import Path
import sys
import time

rows = []
for path in Path('/proc').iterdir():
    if not path.name.isdigit():
        continue
    try:
        name = (path / 'comm').read_text().strip()
        if name not in ('cc1plus', 'tomokv', 'at15b-post', 'redis-server'):
            continue
        rows.append(dict(pid=int(path.name), name=name, cwd=str((path / 'cwd').resolve()),
                         argv=(path / 'cmdline').read_bytes().decode().split('\0')[:-1],
                         threads={task.name: sorted(os.sched_getaffinity(int(task.name)))
                                  for task in (path / 'task').iterdir()}))
    except (OSError, ProcessLookupError):
        continue
Path(sys.argv[1]).write_text(json.dumps(dict(wall_ns=time.time_ns(), processes=rows), indent=2) + '\n')
print('processes', len(rows), 'compilers', sum(row['name'] == 'cc1plus' for row in rows))
