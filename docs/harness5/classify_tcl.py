"""Build an auditable classification table from retained upstream event receipts."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSTREAM = Path('/home/user/Projects/redis')
DESIGN = 'unsupported by design'
INTERNAL = 'Redis-internal assumption'
REAL = 'REAL compatibility defect'


def read(name):
    return json.loads(gzip.decompress((HERE / name).read_bytes()))


def subsystem(unit):
    return {'unit/functions':'src/cmd/functions.cc', 'unit/scripting':'src/cmd/scripting.cc',
        'unit/multi':'src/cmd/multi.inc / multi_admin.cc', 'unit/other':'src/net (RESET/connection state)',
        'unit/tracking':'src/net (client tracking)', 'unit/pause':'src/net (CLIENT PAUSE)',
        'unit/slowlog':'src/cmd/slowlog.cc', 'unit/type/stream':'src/cmd/t_stream.cc',
        'unit/type/stream-cgroups':'src/cmd/t_stream_groups.cc', 'unit/type/zset':'src/cmd/t_zset.cc',
        'unit/dump':'src/store/object_idle.h / RESTORE', 'unit/introspection-2':'command statistics / scripting',
        'unit/latency-monitor':'LATENCY / command histogram accounting',
        'unit/info-command':'INFO section selection', 'unit/lazyfree':'src/cmd/multi_admin.cc',
        'unit/expire':'CONFIG / persistence', 'unit/sort':'src/cmd/scripting.cc',
        'unit/introspection':'CLIENT / INFO accounting'}.get(unit, 'command dispatch / configuration')


def classify(unit, name, data, isolated):
    """Rules are visible here; the receipts, not the rule, remain the evidence."""
    err = [] if not isolated else [e['data'] for e in isolated['results']['2s']['selected'] if e['status']=='err']
    detail = '\n'.join(err) or data
    text = (name + '\n' + detail).lower()
    if '/moduleapi/' in unit:
        return DESIGN, 'Module API surface is deliberately absent; module tests also need native test .so fixtures.'
    if "unknown command 'module'" in text or name == 'RESP3 attributes on RESP2':
        return DESIGN, 'Requires MODULE HELP or Redis DEBUG PROTOCOL; deliberately unsupported internals/surface.'
    if name in ('EVAL - Scripts do not block on wait', 'EVAL - Scripts do not block on waitaof'):
        return DESIGN, 'WAIT/WAITAOF replication acknowledgement surface is deliberately absent.'
    if re.search(r'repl-ping|replicaof|slaveof|\bsync\b|min-replicas|masteruser|cluster|sentinel|migrate', text) or re.search(r'replicat|replica|propagat', name.lower()):
        return DESIGN, 'Replication, cluster, or cross-server migration surface; outside the single-node target.'
    if 'debug' in text and ('unknown subcommand' in text or 'debug digest' in text or 'r debug' in text or 'r $level debug' in text):
        return DESIGN, 'Test requires a Redis DEBUG implementation/internal representation.'
    if 'calls can not be nested' in text or 'expected non-negative integer but got' in text:
        return INTERNAL, 'Upstream external-server test lifecycle/controller assumption; not a command-semantic verdict.'
    if isolated:
        selected = isolated['results']['2s']['selected']
        if selected and all(e['status']=='ok' for e in selected):
            return INTERNAL, 'Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect).'
    # A public MULTI rejection remains a compatibility failure even when a test
    # happens to live in lazyfree.tcl. Do not dismiss it as memory instrumentation.
    if 'not allowed inside a transaction' in text:
        return REAL, 'Public command is rejected in MULTI; see the isolated test and both replies.'
    if re.search(r'list-compress-depth|quicklist|encoding|shared objects|hll-sparse|rdb-key-save-delay', text):
        return INTERNAL, 'Redis storage layout, compression, encoding threshold, or internal save-delay control.'
    if unit in ('unit/querybuf', 'unit/replybufsize') or re.search(r'lazyfree|lazyfreed|used_memory|dirty|qbuf=|query buffer', text):
        return INTERNAL, 'Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim.'
    if unit == 'unit/type/stream' and re.search(r'maxlen|limit|xtrim with ~', name.lower()):
        return INTERNAL, 'Approximate stream trimming asserts Redis radix-node packing/granularity.'
    if unit == 'unit/latency-monitor' and 'instruction limit' in text:
        return INTERNAL, 'Artificial timing workload exceeds TomoKV’s script instruction budget.'
    if isolated:
        a, b = isolated['results']['2s']['selected'], isolated['results']['redis']['selected']
        if a and all(e['status']=='ok' for e in a):
            return INTERNAL, 'Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect).'
        if b and all(e['status']=='ok' for e in b) and any(e['status']=='err' for e in a):
            return REAL, 'Same selected upstream case fails on TomoKV and passes on Redis 7.4.10.'
        if any(e['status']=='err' for e in b):
            return INTERNAL, 'Fresh exact-name case also fails on Redis: prerequisite/test-state assumption; full-file evidence retained.'
        if not a or not b:
            return INTERNAL, 'Selected assertion is unreachable without prior test setup; external-suite lifecycle evidence retained.'
    if not name or 'executing test client:' in text:
        return INTERNAL, 'File setup/teardown failed outside a named assertion; raw exception and unreached coverage retained.'
    # These were deliberately not sent to the isolation runner when their full
    # stack already identified DEBUG/replication. Keep any remaining difference
    # visible for review instead of silently turning it into an unsupported API.
    return REAL, 'Observed full-file compatibility failure; exact upstream sequence is the reproducer.'


def main():
    reports = {m:read(f'redis-tcl-{m}.json.gz') for m in ('2s','1s','redis')}
    isolated = read('redis-tcl-isolated.json.gz')
    cases = {(r['file'],r['test']):r for r in isolated}
    extra = HERE / 'redis-tcl-prefix.json.gz'
    if extra.exists():
        for r in read(extra.name):
            a,b = r['results']['2s']['selected'],r['results']['redis']['selected']
            if a and b and all(e['status']=='ok' for e in b): cases[(r['file'],r['test'])]=r
    rows, files = [], []
    for mode, report in reports.items():
        for r in report['rows']:
            counts = Counter()
            done = False
            for index,e in enumerate(r['events']):
                if e['status']=='done': done=True
                if e['status'] not in ('err','exception'): continue
                if done and e['status']=='exception' and 'read $::test_server_fd $bytes' in e['data']: continue
                name=e['test'].split(' in tests/')[0]
                iso=cases.get((r['file'],name))
                category,reason=classify(r['file'],name,e['data'],iso)
                counts[category]+=1
                if mode!='redis':
                    rows.append(dict(mode=mode,file=r['file'],test=name or '<file setup/teardown>',
                        category=category,reason=reason,subsystem=subsystem(r['file']) if category==REAL else None,
                        event_index=index,detail=e['data'],isolation_case=iso.get('case') if iso else None,
                        reproduction=([r['file'],name,iso.get('selected_names',[name])] if iso else [r['file'],name]),
                        oracle_isolated=[e['status'] for e in iso['results']['redis']['selected']] if iso else None))
            files.append(dict(mode=mode,file=r['file']+'.tcl',passed=r['passed'],failed=r['failed'],skipped=r['skipped'],
                complete=r['complete'],exit_code=r['exit_code'],error=r['error'],seconds=r['seconds'],
                classified_failures=dict(counts),teardown_exceptions=r['teardown_exceptions']))
    sources={str(p.relative_to(UPSTREAM/'tests')):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((UPSTREAM/'tests').rglob('*.tcl')) if 'tmp' not in p.parts}
    attempted=set(reports['2s']['inventory'])
    not_units=[dict(file=n,sha256=h,status='not an external-server unit/integration input') for n,h in sources.items()
               if n.removesuffix('.tcl') not in attempted]
    summary=dict(schema=1,source_base='3700b51d7',redis_version='7.4.10',
        binary_sha256={m:r['binary_sha256'] for m,r in reports.items()},
        files=files,other_tcl_files=not_units,all_tcl_sha256=sources,
        interpretation='Counts are observed assertions/events, not unique bugs. Unreached assertions are not fabricated as skips.')
    (HERE/'redis-tcl-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (HERE/'redis-tcl-failures.json.gz').write_bytes(gzip.compress(json.dumps(rows,sort_keys=True).encode(),mtime=0))
    real={}
    for row in rows:
        if row['category']==REAL: real.setdefault((row['file'],row['test']),row)
    reproduction=[dict(id=f'R{i:03}',**row) for i,row in enumerate(real.values(),1)]
    (HERE/'redis-tcl-real-cases.json').write_text(json.dumps(reproduction,indent=2)+'\n')
    unique={}
    for row in rows:
        key=(row['file'],row['test'],row['category'],row['reason'])
        unique.setdefault(key,[]).append(row)
    def safe(s): return s.replace('|','\\|').replace('\n',' ')
    lines=['# Redis 7.4.10 external Tcl survey','',
      'Source baseline: `3700b51d7`; no production changes. Both servers used fresh per-file data directories,',
      '16 databases, `--singledb`, and the supplied upstream tests. TomoKV used 16 shards;',
      '2s used eight CPUs at ratio 6:2. All processes were confined to CPUs 32–47 and listener ports 45800–45899.',
      'The suite driver copies upstream into this worktree; assertion bodies remain unchanged. An event observer',
      'records test packets, and includes `unit/moduleapi` in discovery. Native Redis is the 7.4.10 oracle.', '',
      f'The supplied tree has **{len(sources)} Tcl files total, {len(attempted)} executable unit/integration inputs**.',
      f'The remaining {len(not_units)} files are support/other harness inputs (including the separate cluster harness),',
      'listed individually in [the machine summary](redis-tcl-summary.json). They are not 71 silently skipped unit tests.', '',
      '| Server | Passed | Failed events | Explicit skips | Files attempted | Files interrupted |',
      '|---|---:|---:|---:|---:|---:|']
    for mode,report in reports.items():
        lines.append('| '+mode+' | '+' | '.join(str(sum(r[k] for r in report['rows'])) for k in ('passed','failed','skipped'))+
                     f" | {len(report['rows'])} | {sum(not r['complete'] for r in report['rows'])} |")
    lines += ['', 'These are observations, **not counts of independent defects or a compatibility percentage**.',
      'External mode skips process-owning tests. A setup error or blocked test can prevent later assertions from running;',
      'unreached assertions are not counted as passes or skips. The 240 s per-file and 60 s upstream idle deadlines',
      'bound the survey. Ordinary post-`done` controller EOF exceptions also occur on Redis and are retained separately.',
      'Every assertion failure and pre-completion exception remains in the table and machine evidence.', '',
      'Raw receipts: [2s](redis-tcl-2s.json.gz), [1s](redis-tcl-1s.json.gz),',
      '[Redis](redis-tcl-redis.json.gz), [fresh exact-name comparisons](redis-tcl-isolated.json.gz).',
      'The receipts contain the executable SHA-256, exact argv, every event and per-file elapsed time.', '',
      '## Reproducing the real compatibility differences','',
      'Each `R` entry in [redis-tcl-real-cases.json](redis-tcl-real-cases.json) names the failing test, suspected subsystem,',
      'both-server evidence and the smallest upstream selection used in the fresh-server check. Error-message differences',
      'are included as compatibility differences; they do not imply corrupted stored values. Related tests can share one cause.',
      'Selections with prerequisite names retain that context; they are not claimed to be irreducible protocol transcripts.', '',
      'To rerun one entry, write its `reproduction` array inside a JSON list and invoke:', '',
      '```sh',
      'taskset -c 32-39 python3 docs/harness5/isolate_tcl.py --cases build/one-case.json \\',
      '  --output build/one-case --cores 32-39 --port 45820 --baseport 45853',
      '```','',
      'This boots TomoKV and Redis in turn and uses `./runtest --host 127.0.0.1 --port 45820 --singledb',
      '--single FILE --only EXACT_TEST_NAME` (plus explicit prerequisite names when present).',
      'The helper retains both selected-test results and command/reply traces. Full-file results cover both TomoKV modes.', '',
      '| ID | Upstream file / test | Suspected subsystem |', '|---|---|---|']
    for r in reproduction:lines.append(f"| {r['id']} | {safe(r['file']+': '+r['test'])} | {safe(r['subsystem'])} |")
    lines += ['', '## Classification of every observed TomoKV failure','',
      'Repeated parameterized instances and both modes are grouped only for display. The exact mode, event index, stack,',
      'classification and reproduction are retained for every occurrence in [redis-tcl-failures.json.gz](redis-tcl-failures.json.gz).',
      'A failure that passes in isolation is recorded as a test-state/cleanup assumption, not counted again as an independent defect.', '',
      '| File / test | Mode(s); occurrences | Class | Evidence / limitation |', '|---|---|---|---|']
    for (unit,name,category,reason),items in unique.items():
        lines.append(f"| {safe(unit+': '+name)} | {','.join(sorted(set(r['mode'] for r in items)))}; {len(items)} | {category} | {safe(reason)} |")
    lines += ['', '## Regression job','',
      '`GATE_ONLY_JOBS=redis_tcl` runs seven complete passing files, **115 assertions in each mode**.',
      'The frozen manifest binds upstream file/support hashes and the complete nonempty multiset of passing assertion names.',
      'A failure, missing assertion, rename, duplicate, skip replacing a pass, timeout, or changed upstream input fails the job.',
      'The gate job uses exactly its server port and one controller port; it cannot scan into another slot.',
      'UTF-8 decoding is explicit because the gate otherwise uses `LC_ALL=C`.', '',
      'The two private rows are prerequisites of the existing `compat2 autharity` public row, before the quick exit.',
      'Missing or failed completion makes that existing row red; serverless controls exercise the missing-completion path.',
      '**DQ=0, DF=0.** No `EXPECT_*` constant or public row count changes.',
      'This subset is a regression guard, not certification of the failing, skipped, or unreached remainder.',
      'Gate results: [passing selected job](tcl-gate/final/gate.log). The first attempt’s locale refusal is retained alongside it.', '']
    (HERE/'redis-tcl-suite.md').write_text('\n'.join(lines))
    print(len(rows),'failure occurrences;',len(real),'distinct REAL test names;',Counter(r['category'] for r in rows))

if __name__=='__main__':main()
