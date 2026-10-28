#!/usr/bin/env python3
import json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT);os.sched_setaffinity(0,set(range(64,96)))
while not Path('docs/wave9/jobs/final-selftest2.json').exists():time.sleep(10)
m=json.loads(Path('docs/wave9/correctness-matrix.json').read_text())
r=subprocess.run(['python3','docs/wave9/run_jobs.py','final-additional',*m['additional_once'],'--single-slot','--server-start','64','--port','20020'])
raise SystemExit(r.returncode)
