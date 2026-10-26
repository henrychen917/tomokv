"""Build the Redis 7.4.10 Tcl-suite report from retained receipts and the reviewed triage.

Inputs (all in docs/harness5 unless noted):
  redis-tcl-{2s,1s,redis}.json.gz   full-file survey receipts (every observer event)
  redis-tcl-reach.json.gz           interrupted files rerun with every hung test skipped
                                    (final pass: same skip list for 2s, 1s and Redis)
  redis-tcl-reach-discovery.json.gz which test hung in which discovery attempt
  triage/{A,B1,B2,MOD}.json         reviewed per-test classification and root causes
  redis-tcl-repros.json             minimal protocol reproductions (repro_tcl.py output)
  ../../tests/redis_tcl_passing.json the gated passing subset
Outputs: redis-tcl-suite.md, redis-tcl-summary.json, redis-tcl-failures.json.gz.
Every failing or hung test observed on TomoKV must have exactly one triage entry;
a missing or duplicated entry is a hard error, never a silent "unclassified" row.
"""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSTREAM = Path('/home/user/Projects/redis')
CLASSES = ('unsupported by design', 'Redis-internal assumption', 'REAL compatibility defect')
MODES = ('2s', '1s', 'redis')


def gz(name):
    return json.loads(gzip.decompress((HERE / name).read_bytes()))


def tname(event):
    return event['test'].split(' in tests/')[0]


def counts(row):
    """passed/failed/skipped exactly as the gate counts them (post-done EOF excluded)."""
    result, done = Counter(), False
    for event in row['events']:
        status = event['status']
        if status == 'done':
            done = True
        elif done and status == 'exception' and 'read $::test_server_fd' in event['data']:
            result['teardown_exceptions'] += 1
        elif status in ('err', 'exception'):
            result['failed'] += 1
        elif status == 'ok':
            result['passed'] += 1
        elif status in ('skip', 'ignore'):
            result['skipped'] += 1
    return result


def failures(row):
    done, out = False, []
    for index, event in enumerate(row['events']):
        if event['status'] == 'done':
            done = True
        if event['status'] not in ('err', 'exception'):
            continue
        if done and event['status'] == 'exception' and 'read $::test_server_fd' in event['data']:
            continue
        out.append((index, tname(event) or '<file setup/teardown>', event['status'], event['data']))
    return out


def hung(row):
    open_tests = []
    for event in row['events']:
        name = tname(event)
        if event['status'] == 'testing':
            open_tests.append(name)
        elif event['status'] in ('ok', 'err', 'skip', 'ignore') and name in open_tests:
            open_tests.remove(name)
    return open_tests[-1] if open_tests else None


def safe(text):
    text = str(text).replace('|', '\\|').replace('\r\n', ' ').replace('\n', ' ')
    # Upstream names and replies can carry NUL/CR/control bytes (e.g. "test\\0test"): show them escaped.
    return ''.join(c if c >= ' ' or c == '\t' else f'\\x{ord(c):02x}' for c in text)


def argv_text(step):
    if 'sleep' in step:
        return f"(sleep {step['sleep']} s)"
    who = step.get('c', 'a')
    if step.get('close'):
        return f'{who}: (close)'
    if 'send' in step:
        line = ' '.join(json.dumps(v) if (isinstance(v, str) and (not v or any(c in v for c in ' "\\\n\t'))) else str(v)
                        for v in step['send'])
        return f"{who}> {line}" + ('  (no reply yet)' if step.get('read', 1) == 0 else '')
    if 'raw' in step:
        return f"{who}> pipelined: " + '; '.join(resp_commands(step['raw'])) + (
            '  (replies read below)' if step.get('read', 1) == 0 else '')
    return f"{who}: (read pending reply, {step.get('timeout', 2.0)} s)"


def resp_commands(raw):
    """Decode raw RESP request arrays for display; fall back to the literal bytes."""
    out, pos = [], 0
    try:
        while pos < len(raw):
            if raw[pos] != '*':
                raise ValueError
            end = raw.index('\r\n', pos); count = int(raw[pos + 1:end]); pos = end + 2; argv = []
            for _ in range(count):
                end = raw.index('\r\n', pos); size = int(raw[pos + 1:end]); pos = end + 2
                argv.append(raw[pos:pos + size]); pos += size + 2
            out.append(' '.join(argv))
        return out
    except (ValueError, IndexError):
        return [repr(raw)]


def short(value, limit=110):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit - 3] + '...'


SEVERE_DATA = ('STREAM-TRIM-APPROX-LIMIT', 'BLOCK-CHAIN-ASYNC', 'BLOCK-WAKE-ORDER-MULTI', 'SCRIPT-NUMBER-ARG',
               'RESTORE-IDLETIME-FREQ-IGNORED', 'DUMP-STREAM-REFUSED')
OOM_GATE = ('MULTI-OOM-QUEUE', 'MULTI-OOM-EXEC', 'PUBSUB-SUBSCRIBE-NO-DENYOOM', 'FUNCTION-LOAD-DENYOOM',
            'PUBSUB-EVICT-ON-MAXMEMORY')


def read_first(roots, observed, triage):
    hangs = sorted({triage[k]['root'] for k, o in observed.items() if o['hung']})
    for rid in ('FUNCTION-LIST-CRLF', *SEVERE_DATA, *OOM_GATE, *hangs):
        if rid not in roots:
            raise SystemExit(f'read-first list names unknown root {rid}')
    code = lambda ids: ', '.join(f'`{i}`' for i in ids)
    return ('**Read first.** `FUNCTION-LIST-CRLF` lets a client forge a reply on its own connection: the error '
            'reply echoes an argument\'s raw CR/LF, so the next command reads the injected `+INJECTED`. '
            f'Upstream tests hang to the idle deadline (an expected reply, push, block or wake never arrives) under: '
            f'{code(hangs)}; the BLOCK-* ones leave a blocked client unserved. Wrong data or ordering effects: '
            f'{code(SEVERE_DATA)}. Out-of-memory gating gaps: {code(OOM_GATE)}. The remaining roots are error '
            'texts, introspection fields, configuration surface and the deliberate restrictions marked in the last column.')


def main():
    full = {m: {r['file']: r for r in gz(f'redis-tcl-{m}.json.gz')['rows']} for m in MODES}
    reach = gz('redis-tcl-reach.json.gz')
    final = {(r['mode'], r['file']): r for r in reach['rows'] if r.get('phase') == 'final'}
    discovery = gz('redis-tcl-reach-discovery.json.gz')
    interrupted = sorted({f for (_, f) in final})
    triage, roots = {}, {}
    for group in ('A', 'B1', 'B2', 'MOD'):
        data = json.loads((HERE / 'triage' / f'{group}.json').read_text())
        for entry in data['tests']:
            entry['test'] = entry['test'] or '<file setup/teardown>'
            key = (entry['file'], entry['test'])
            if key in triage:
                raise SystemExit(f'duplicate triage entry: {key}')
            if entry['class'] not in CLASSES:
                raise SystemExit(f'bad class for {key}: {entry["class"]}')
            triage[key] = dict(entry, group=group)
        for root in data['roots']:
            if root['id'] in roots:
                raise SystemExit(f'duplicate root id: {root["id"]}')
            roots[root['id']] = dict(root, group=group)
    repros = json.loads((HERE / 'redis-tcl-repros.json').read_text())
    manifest = json.loads((ROOT / 'tests/redis_tcl_passing.json').read_text())

    # Observed TomoKV failures: full-file survey of every file, plus the final reach pass and
    # every hung test (discovery) of the interrupted files.
    observed = defaultdict(lambda: dict(modes=set(), occurrences=[], where=set(), hung=False))
    for mode in ('2s', '1s'):
        for unit, row in full[mode].items():
            for index, name, status, data in failures(row):
                o = observed[(unit, name)]
                o['modes'].add(mode); o['where'].add('full-file')
                o['occurrences'].append(dict(mode=mode, source='full-file', event_index=index, status=status, detail=data))
            name = hung(row)
            if name:
                o = observed[(unit, name)]
                o['modes'].add(mode); o['where'].add('full-file'); o['hung'] = True
                o['occurrences'].append(dict(mode=mode, source='full-file', status='hung (60 s idle deadline)', detail=''))
        for unit in interrupted:
            row = final[(mode, unit)]
            for index, name, status, data in failures(row):
                o = observed[(unit, name)]
                o['modes'].add(mode); o['where'].add('reach')
                o['occurrences'].append(dict(mode=mode, source='reach-final', event_index=index, status=status, detail=data))
    for row in discovery['rows']:
        if row['mode'] == 'redis':
            continue
        name = hung(row)
        if name:
            o = observed[(row['file'], name)]
            o['modes'].add(row['mode']); o['where'].add('reach'); o['hung'] = True
            o['occurrences'].append(dict(mode=row['mode'], source=f"reach-discovery #{row['attempt']}",
                                         status='hung (idle deadline)', detail=''))
    # Failures seen while building the gated subset (same binary, same upstream, skip lists applied).
    for run, history in (('builder run 1', 'redis-tcl-builder-history-run1.json'),
                         ('builder run 2', 'redis-tcl-builder-history.json')):
        for round_row in json.loads((HERE / history).read_text()):
            for unit, mode, name, data in round_row['problems']:
                if name == '<file>' or 'expected non-negative integer but got' in data:
                    continue
                o = observed[(unit, name)]
                o['modes'].add(mode); o['where'].add('builder'); o['hung'] |= data == 'hung'
                o['occurrences'].append(dict(mode=mode, source=f"{run} round {round_row['round']}",
                                             status='hung' if data == 'hung' else 'err', detail=data))
    missing = sorted(k for k in observed if k not in triage)
    extra = sorted(k for k in triage if k not in observed)
    if missing:
        raise SystemExit('failing tests without a triage entry:\n' + '\n'.join(map(str, missing)))
    if extra:
        raise SystemExit('triage entries for tests never observed failing:\n' + '\n'.join(map(str, extra)))
    for key, entry in triage.items():
        if entry['root'] not in roots:
            raise SystemExit(f'{key}: unknown root {entry["root"]}')

    # Per-file results: survey and effective (reach-final for interrupted files).
    files = []
    for unit in sorted(full['2s']):
        row = dict(file=unit + '.tcl', interrupted_on_tomokv=unit in interrupted)
        for mode in MODES:
            c = counts(full[mode][unit])
            row[f'survey_{mode}'] = dict(passed=c['passed'], failed=c['failed'], skipped=c['skipped'],
                complete=full[mode][unit]['complete'], seconds=round(full[mode][unit]['seconds'], 2),
                hung=hung(full[mode][unit]))
            if unit in interrupted:
                f = final[(mode, unit)]; cf = counts(f)
                row[f'reach_{mode}'] = dict(passed=cf['passed'], failed=cf['failed'], skipped=cf['skipped'],
                    complete=f['complete'], seconds=round(f['seconds'], 2), skip_tests=f['skip_tests'],
                    extra_runtest_args=f.get('extra_runtest_args', []))
        per_class = Counter()
        for (u, name), o in observed.items():
            if u == unit:
                per_class[triage[(u, name)]['class']] += 1
        row['failing_tests_by_class'] = dict(per_class)
        files.append(row)

    def effective(mode):
        total = Counter()
        for unit in full[mode]:
            row = final[(mode, unit)] if unit in interrupted else full[mode][unit]
            total.update(counts(row))
        return total

    # Root-cause aggregation.
    by_root = defaultdict(list)
    for key, entry in triage.items():
        by_root[entry['root']].append(key)
    class_tests = Counter(triage[k]['class'] for k in observed)
    class_occ = Counter()
    for k, o in observed.items():
        class_occ[triage[k]['class']] += len(o['occurrences'])
    real_roots = [r for r in roots.values() if r['class'] == CLASSES[2]]
    independent = Counter(triage[k]['class'] for k in observed if not triage[k].get('cascade_of'))

    sources = {str(p.relative_to(UPSTREAM / 'tests')): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((UPSTREAM / 'tests').rglob('*.tcl')) if 'tmp' not in p.parts}
    attempted = set(gz('redis-tcl-2s.json.gz')['inventory'])
    lines = ['# Redis 7.4.10 Tcl suite against TomoKV', '',
      'Source baseline `3700b51d7` (no production change in this lane); TomoKV executable '
      f"`{reach['binary_sha256'][:16]}…` (`build/tomokv`, binary-neutral IDENTICAL to "
      '`bench-bins/tomokv-headline-3700b51d7`); oracle Redis 7.4.10 '
      f"`{reach['redis_sha256'][:16]}…`. External-server mode: `./runtest --host 127.0.0.1 --port P "
      '--singledb --single FILE --clients 1`, one fresh server per file, 16 databases, TomoKV 16 shards, '
      '2s at ratio 6:2 on eight CPUs. All runs were confined to CPUs 32–47 and ports 45800–45899.', '',
      f"The tree has {len(sources)} `.tcl` files: {len(attempted)} executable unit/integration files (all attempted, "
      f'including `unit/moduleapi`) and {len(sources) - len(attempted)} support files and the separate cluster harness '
      '(listed in the summary).', '',
      '## Results', '',
      '| Server | Passed | Failed | Skipped | Files | Files interrupted (hang/abort) |', '|---|---:|---:|---:|---:|---:|']
    for mode in MODES:
        c = Counter()
        for r in full[mode].values():
            c.update(counts(r))
        lines.append(f"| {mode} full-file survey | {c['passed']} | {c['failed']} | {c['skipped']} | "
                     f"{len(full[mode])} | {sum(not r['complete'] for r in full[mode].values())} |")
    for mode in MODES:
        c = effective(mode)
        lines.append(f"| {mode} with the {len(interrupted)} interrupted files reached | {c['passed']} | "
                     f"{c['failed']} | {c['skipped']} | {len(full[mode])} | 0 |")
    lines += ['',
      f"Seven files never completed on TomoKV in the full-file run: {', '.join('`'+u+'`' for u in interrupted)}. "
      'Six stopped at a test that waited forever for a reply (60 s idle deadline); `unit/type/stream` stopped at a '
      'file-level `CONFIG SET appendonly yes` (immutable on TomoKV). Those files were rerun with every hung test named '
      'in `--skipfile` (and `--tags -needs:debug` for `unit/type/stream`, which removes only its appendonly blocks); '
      'the final pass used the same skip list for 2s, 1s and Redis, and Redis passes every assertion of it except one '
      'state-dependent `unit/type/list` test. Rows 4–6 replace those files by the reached run. Counts are '
      'assertion events, not independent defects; external mode skips the tests that need to own the server process.', '',
      '## Classification', '',
      '| Class | Failing tests | of which independent (not a cascade) | Failure events (both modes) |', '|---|---:|---:|---:|']
    for cls in CLASSES:
        lines.append(f'| {cls} | {class_tests[cls]} | {independent[cls]} | {class_occ[cls]} |')
    lines.append(f'| **total** | **{sum(class_tests.values())}** | {sum(independent.values())} | {sum(class_occ.values())} |')
    lines += ['', 'A cascade is a test that fails only because an earlier test left state behind; it carries its root '
      "test's class and names it. Hangs count as failures.", '',
      f'## REAL compatibility defects ({len(real_roots)} root causes)', '',
      'One row per root cause. Each has a minimal reproduction in [redis-tcl-repros.json](redis-tcl-repros.json) '
      '(cases in [redis-tcl-repro-cases.json](redis-tcl-repro-cases.json)), replayed on fresh TomoKV 2s, TomoKV 1s '
      'and Redis 7.4.10 servers by `docs/harness5/repro_tcl.py`; the verdict compares the typed RESP replies. '
      '“Design note” marks deliberate TomoKV restrictions outside the owner’s unsupported-by-design list; they are '
      'still client-visible differences and are listed for the maintainer, not judged here.', '',
      read_first(roots, observed, triage), '',
      '| ID | Defect | Tests | Modes | Suspected subsystem | Reproduction (verdict 2s/1s) | Redis 7.4.10 | TomoKV | Design note |',
      '|---|---|---:|---|---|---|---|---|---|']
    for root in sorted(real_roots, key=lambda r: r['id']):
        case = repros['cases'].get(root.get('repro_case') or '', {})
        steps = '<br>'.join(safe(argv_text(s)) for s in case.get('steps', [])) or 'see notes'
        verdict = case.get('verdict', {})
        v = f" ({verdict.get('2s', '?')}/{verdict.get('1s', '?')})" if case else (
            f" per-boot probe: {root['probe']}" if root.get('probe') else ' (no protocol case)')
        if not case and root.get('probe'):
            steps = 'WATCH dstset{t}; MULTI; SADD dstset{t} c; (second client) SMOVE srcset{t} dstset{t} a where dstset{t} already holds a; EXEC'
        also = [a['repro_case'] for a in root.get('also_found_as', []) if a.get('repro_case')]
        if also:
            v += '<br>also: ' + ', '.join(f"`{a}` ({'/'.join(repros['cases'].get(a, {}).get('verdict', {}).get(m, '?') for m in ('2s', '1s'))})" for a in also)
        lines.append(f"| {root['id']} | {safe(root['title'])} | {len(by_root[root['id']])} | {','.join(root.get('modes', []))} | "
                     f"{safe(root.get('subsystem', ''))} | {steps}{v} | {safe(root.get('redis', ''))} | "
                     f"{safe(root.get('tomokv', ''))} | {safe(root.get('design_note') or '')} |")
    lines += ['', '## Other root causes', '', '| ID | Class | Cause | Tests |', '|---|---|---|---:|']
    for root in sorted((r for r in roots.values() if r['class'] != CLASSES[2]), key=lambda r: (r['class'], r['id'])):
        lines.append(f"| {root['id']} | {root['class']} | {safe(root['title'])} | {len(by_root[root['id']])} |")
    lines += ['', '## Every failing test', '',
      'Parameterized repeats of one test name are one row; both modes, every event and stack are in '
      '[redis-tcl-failures.json.gz](redis-tcl-failures.json.gz).', '',
      '| File | Test | Modes | Where | Class | Root / cascade of | Basis |', '|---|---|---|---|---|---|---|']
    for key in sorted(observed):
        entry, o = triage[key], observed[key]
        where = '+'.join(sorted(o['where'])) + (' (hung)' if o['hung'] else '')
        cause = entry['root'] + (f"; cascade of {entry['cascade_of']}" if entry.get('cascade_of') else '')
        lines.append(f"| {key[0]} | {safe(key[1])} | {','.join(sorted(o['modes']))} | {where} | {entry['class']} | "
                     f"{safe(cause)} | {safe(entry.get('basis', ''))} |")
    gated = sum(len(f['passed_tests']) for f in manifest['files'].values())
    skipped = sum(len(f.get('skip_tests', ())) for f in manifest['files'].values())
    lines += ['', '## Regression job', '',
      f"`GATE_ONLY_JOBS=redis_tcl` runs **{len(manifest['files'])} upstream files, {gated} assertions in each mode** "
      f"(2s then 1s), listed exactly in [tests/redis_tcl_passing.json](../../tests/redis_tcl_passing.json) with the "
      f"{skipped} named known failures each file skips. See MEASURE-REQUEST-harness5.md for its verification.", '']
    lines += ['## Files', '',
      '- [redis-tcl-summary.json](redis-tcl-summary.json): passed/failed/skipped per file and server, survey and reach.',
      '- [redis-tcl-failures.json.gz](redis-tcl-failures.json.gz): every failure event with mode, stack, class and root.',
      '- [triage/](triage/): the reviewed per-test classification (four groups) and root causes.',
      '- Raw receipts: [2s](redis-tcl-2s.json.gz), [1s](redis-tcl-1s.json.gz), [Redis](redis-tcl-redis.json.gz), '
      '[reach](redis-tcl-reach.json.gz), [reach discovery](redis-tcl-reach-discovery.json.gz), '
      '[exact-name isolation reruns](redis-tcl-isolated.json.gz) (2s and Redis).',
      '- Tools: `tests/redis_tcl.py` (driver), `reach_tcl.py`, `isolate_tcl.py`, `repro_tcl.py`, '
      '`build_tcl_manifest.py`, `tcl_report.py` (this report).', '']
    (HERE / 'redis-tcl-suite.md').write_text('\n'.join(lines))

    summary = dict(schema=2, source_base='3700b51d7', redis_version='7.4.10',
        binary_sha256=dict(tomokv=reach['binary_sha256'], redis=reach['redis_sha256']),
        totals={f'survey_{m}': dict(sum((counts(r) for r in full[m].values()), Counter())) for m in MODES} |
               {f'reached_{m}': dict(effective(m)) for m in MODES},
        classification=dict(tests=dict(class_tests), independent=dict(independent), events=dict(class_occ)),
        roots=[dict(id=r['id'], **{k: r.get(k) for k in ('class', 'title', 'subsystem', 'design_note', 'repro_case',
               'redis', 'tomokv', 'modes')}, tests=[f'{u}: {n}' for u, n in sorted(by_root[r['id']])],
               repro_verdict=repros['cases'].get(r.get('repro_case') or '', {}).get('verdict'))
               for r in sorted(roots.values(), key=lambda r: r['id'])],
        tests=[dict(file=u, test=n, modes=sorted(observed[(u, n)]['modes']), where=sorted(observed[(u, n)]['where']),
                    hung=observed[(u, n)]['hung'], **{k: triage[(u, n)].get(k) for k in ('class', 'root', 'cascade_of', 'basis')})
               for u, n in sorted(observed)],
        files=files,
        gate_subset=dict(files=len(manifest['files']), assertions_per_mode=gated, named_known_failures=skipped),
        other_tcl_files=[dict(file=n, sha256=h) for n, h in sources.items() if n.removesuffix('.tcl') not in attempted],
        interpretation='Counts are observed assertion events, not unique defects. Interrupted files are reported '
                       'both as surveyed and as reached with their hung tests skipped.')
    (HERE / 'redis-tcl-summary.json').write_text(json.dumps(summary, indent=1) + '\n')
    rows = []
    for (u, n), o in sorted(observed.items()):
        for occ in o['occurrences']:
            rows.append(dict(file=u, test=n, **occ, **{k: triage[(u, n)].get(k) for k in ('class', 'root', 'cascade_of')}))
    (HERE / 'redis-tcl-failures.json.gz').write_bytes(gzip.compress(json.dumps(rows, sort_keys=True).encode(), mtime=0))
    print(len(observed), 'failing tests;', dict(class_tests), len(real_roots), 'REAL roots')


if __name__ == '__main__':
    main()
