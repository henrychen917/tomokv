#!/usr/bin/env python3
"""Select every gate job whose work touches maxmemory, eviction, CONFIG, DENYOOM or pub/sub.

Source inventory only (no server, build or gate run). For each full-tier job the
job's shell body (job_body dispatch, job_<name>, or the inline evict-/differ- arms)
and every tests/ or tools/ script that body names are scanned for the five keyword
families. Output: docs/wave12/selected-jobs.json with the matched evidence.
"""
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / 'tests/gate.sh').read_text()
FAMILIES = {
    'maxmemory': re.compile(r'maxmemory', re.I),
    'eviction': re.compile(r'evict', re.I),
    'config': re.compile(r'''\bCONFIG\b['"]?\s*,?\s*['"]?(?:SET|GET|REWRITE|RESETSTAT)|'CONFIG'|"CONFIG"|config_set|config set''', re.I),
    'denyoom': re.compile(r'denyoom|OOM command|-OOM', re.I),
    'wave12': re.compile(r'flush|snapshot|bgsave|aof|shutdown|txnorder|script|flip|multidb|atomic|tracking|keyspace', re.I),
    'copy-build': re.compile(r'build.py|build_from|copytree|git archive|source.*build|source_identity|production_units', re.I),
    'pubsub': re.compile(r'\b[PS]?SUBSCRIBE\b|\bPUBLISH\b|\bSPUBLISH\b|pubsub|keyspace notification|notify-keyspace', re.I),
}


def job_names(tier='full'):
    plan = GATE[GATE.index('plan_jobs(){'):GATE.index('\nstart_workers(){')]
    script = 'set -eu\n' + plan + '\nplan_jobs\nprintf "%s\\n" "${JOB_NAMES[@]}"\n'
    out = subprocess.run(['bash', '-c', script], cwd=ROOT, text=True, capture_output=True,
                         env=dict(os.environ, TIER=tier), check=True)
    return out.stdout.split()


def bodies():
    starts = list(re.finditer(r'^(job_\w+|feature_\w+_job)\(\)\{', GATE, re.M))
    out = {}
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else GATE.index('\n# ---- 0. preflight:')
        out[m[1]] = GATE[m.end():end]
    return out


def body_for(name, funcs):
    dispatch = funcs['job_body']
    for pattern, target in re.findall(r'^    ([\w*-]+)\) (\w+)', dispatch, re.M):
        if re.fullmatch(pattern.replace('*', '.*'), name) and target in funcs:
            return target, funcs[target]
    for arm in ('differ-*', 'evict-*', 'flipctl'):
        if re.fullmatch(arm.replace('*', '.*'), name):
            m = re.search(r'^    ' + re.escape(arm) + r'\)(.*?);;', dispatch, re.M | re.S)
            return 'job_body:' + arm, m[1]
    return 'job_' + name, funcs.get('job_' + name, '')


def scripts(text):
    found = set()
    for path in re.findall(r'(?:tests|tools)/[\w./-]+\.(?:py|sh|tcl|cc)', text):
        p = ROOT / path
        if p.exists():
            found.add(path)
    return sorted(found)


def main():
    funcs = bodies()
    full, quick = job_names('full'), set(job_names('quick'))
    rows = []
    for name in full:
        fn, body = body_for(name, funcs)
        files = scripts(body)
        texts = {'gate.sh:' + fn: body} | {f: (ROOT / f).read_text(errors='replace') for f in files}
        hits = {}
        for family, rx in FAMILIES.items():
            where = sorted(src for src, t in texts.items() if rx.search(t))
            if where:
                hits[family] = where
        rows.append(dict(job=name, tier='quick' if name in quick else 'full-only', function=fn,
                         scripts=files, families=hits))
    selected = [r for r in rows if r['families']]
    out = dict(rule='job body or a tests/tools script it names matches a family regex',
               families={k: v.pattern for k, v in FAMILIES.items()},
               total_jobs=len(rows), selected=len(selected),
               jobs=selected, unselected=[r['job'] for r in rows if not r['families']])
    (ROOT / 'docs/wave12/selected-jobs.json').write_text(json.dumps(out, indent=1) + '\n')
    for r in selected:
        print(r['tier'], r['job'], ','.join(sorted(r['families'])))
    print(len(selected), 'of', len(rows))


if __name__ == '__main__':
    main()
