#!/usr/bin/env python3
"""Archive completed native correctness jobs, including every failed attempt.

This records partial ledgers, never a full gate receipt. Large logs remain in
build/ with hashes; directed legs and differential coverage stay reviewable.
"""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/at412c/proof'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    records = []
    for row in json.loads((ROOT / 'build/at412c/proof/runs.json').read_text()):
        run = Path(row['run_dir'])
        dest = OUT / (Path(row['log']).stem + '-' + run.name)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row['log'], dest / 'output.log')
        for name in ('ledger.partial', 'plan.sh', 'differ-plan.json',
                     'differ-split-fold.json', 'differ-armed-fold.json'):
            if (run / name).exists():
                shutil.copy2(run / name, dest / name)
        jobs = []
        for job in sorted((run / 'jobs').iterdir()):
            assert (job / 'done').exists(), ('unfinished job in completed run', job)
            rc, passed, failed = map(int, (job / 'done').read_text().split())
            item = dict(name=job.name, returncode=rc, passed=passed, failed=failed,
                        source=str(job))
            ledger = job / 'ledger'
            if ledger.exists() and ledger.stat().st_size:
                shutil.copy2(ledger, dest / (job.name + '.ledger'))
            files = []
            for file in sorted(job.rglob('*')):
                if not file.is_file():
                    continue
                relative = file.relative_to(job)
                keep = file.name in ('results.json', 'result.json', 'seeds.json',
                                     'legs.tsv', 'complete.json', 'stream.json',
                                     'argv.json', 'exit.json', 'quiescence.json',
                                     'command-coverage.json')
                keep |= file.name.endswith('.coverage.json')
                log = file.suffix in ('.txt', '.log') or file.name.startswith('gate-srv-')
                if not (keep or log):
                    continue
                size = file.stat().st_size
                with file.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                files.append(dict(path=str(relative), bytes=size, sha256=digest))
                # Preserve all small logs for failures and the requested units;
                # huge native traces remain identifiable without bloating git.
                if keep or (log and size <= 256 * 1024 and
                            (failed or job.name.startswith(('at412-', 'txnorder', 'differ-')))):
                    target = dest / job.name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
            save(dest / (job.name + '-files.json'), files)
            if job.name.startswith('at412-') and job.name != 'at412-owner':
                result = job / job.name / 'results.json'
                if result.exists():
                    legs = json.loads(result.read_text())
                    item['legs'] = len(legs)
                    item['passed_legs'] = sum(bool(x.get('pass')) for x in legs)
                    item['oracle_legs'] = sum(x['leg'].startswith('redis-') for x in legs)
            if job.name.startswith('differ-'):
                complete = job / 'differ' / 'complete.json'
                if complete.exists():
                    item['differ_complete'] = json.loads(complete.read_text())
                output = job / 'output.log'
                if output.exists():
                    lines = output.read_text().splitlines()
                    item['skipped_legs'] = [line.strip() for line in lines if ' SKIP ' in line]
                    item['coverage_summary'] = [line for line in lines if
                                                line.startswith('DIFFER COMMAND COVERAGE:')]
                item['equivalence'] = []
                for result in sorted((job / 'differ').glob('mode-equivalence-*/results.json')):
                    cells = json.loads(result.read_text())
                    stream = json.loads((result.parent / 'stream.json').read_text())
                    item['equivalence'].append(dict(
                        seed=stream['seed'], cells=len(cells),
                        passed=sum(c['verdict'] == 'ok' for c in cells),
                        reached=sum(bool(c['reached']) for c in cells),
                        engines=sorted({c['knobs']['net-io'] for c in cells}),
                        replies_per_cell=stream['operation_count'],
                        script_drain_boundaries=stream['script_drain_boundaries'],
                        stream_sha256=stream['stream_sha256']))
            jobs.append(item)
        records.append(dict(row, archived=str(dest.relative_to(ROOT)), jobs=jobs))
    save(OUT / 'runs.json', records)
    print('Archived', len(records), 'partial runs;',
          sum(r['rc'] != 0 for r in records), 'failed attempts retained')


if __name__ == '__main__':
    main()
