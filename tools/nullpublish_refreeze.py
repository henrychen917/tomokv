#!/usr/bin/env python3
"""Rebuild and commit the next null campaign's freeze; never run workloads.

Run this on the landed mainline with tools/nullpublish_refreeze.py. All children
inherit cores 112-127. A second invocation on a landed, unchanged freeze is a
no-op. An unlanded refreeze commit still fails the mandatory origin/cpp guard.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPORT = 'MEASURE-REQUEST-nullpublish3.md'
FREEZE = 'build/nullpublish-freeze.json'
MANIFEST = 'build/nullpublish-campaign.sha256'
SCRIPT = 'build/nullpublish-campaign.sh'
INSTRUMENT = 'build/nullpublish-POST.instrument.json'
BUILD_INPUTS = ('src', 'third_party', 'Makefile', 'tools/tailgen')
BEGIN, END = '<!-- nullpublish-freeze:start -->', '<!-- nullpublish-freeze:end -->'
ARTIFACTS = ('build/tomokv-nullpublish-POST', 'build/tailgen-nullpublish-frozen',
             'build/memtier-nullpublish-frozen', INSTRUMENT,
             'tests/headline_cells.txt', 'tests/gate_measurements.json')


def run(root, *argv):
    return subprocess.check_output(argv, cwd=root, stderr=subprocess.STDOUT).decode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2) + '\n'


def campaign(report):
    fences = re.findall(r'```bash\n(.*?)```', report, re.S)
    require(len(fences) == 1, 'report must contain exactly one campaign bash fence')
    require(len(re.findall(r'^FROZEN_COMMIT=[0-9a-f]{40}$', fences[0], re.M)) == 1,
            'campaign needs exactly one frozen commit anchor')
    return fences[0]


def frozen_block(freeze):
    return BEGIN + '\n```json\n' + encoded(freeze) + '```\n' + END


def instrument(root):
    return run(root, sys.executable, 'tests/abba_instrument.py')


def input_identity(root, manifest, generator):
    return dict(build_tree=hashlib.sha256(run(root, 'git', 'ls-tree', '-r', 'HEAD', '--',
                                             *BUILD_INPUTS).encode()).hexdigest(),
                instrument_sha256=hashlib.sha256(manifest.encode()).hexdigest(),
                cells_sha256=sha(root / 'tests/headline_cells.txt'),
                measurements_sha256=sha(root / 'tests/gate_measurements.json'),
                refreeze_sha256=sha(root / 'tools/nullpublish_refreeze.py'),
                campaign_template_sha256=hashlib.sha256(re.sub(r'^FROZEN_COMMIT=[0-9a-f]{40}$',
                    'FROZEN_COMMIT=' + '0' * 40, campaign((root / REPORT).read_text()), flags=re.M).encode()).hexdigest(),
                memtier_sha256=sha(generator))


def generate_script(root):
    """Regenerate the reviewable script only; cannot create/refresh a freeze."""
    script = campaign((root / REPORT).read_text())
    (root / SCRIPT).parent.mkdir(parents=True, exist_ok=True)
    (root / SCRIPT).write_text(script)
    subprocess.run(['bash', '-n', str(root / SCRIPT)], check=True)
    return root / SCRIPT


def check(root, *, current_instrument=None):
    """Serverless campaign preflight; stale bytes must not become a new freeze."""
    freeze = json.loads((root / FREEZE).read_text())
    require(freeze.get('schema') == 3, 'run tools/nullpublish_refreeze.py on landed mainline first')
    report = (root / REPORT).read_text()
    require(frozen_block(freeze) in report, 'freeze JSON differs from committed report')
    script = campaign(report)
    require((root / SCRIPT).read_text() == script, 'campaign script differs from report fence')
    require(f"FROZEN_COMMIT={freeze['source_commit']}\n" in script, 'stale campaign source anchor')
    run(root, 'git', 'merge-base', '--is-ancestor', freeze['source_commit'], 'HEAD')
    run(root, 'git', 'diff', '--exit-code', freeze['source_commit'], '--', *BUILD_INPUTS)
    # Bind the manifest itself to committed provenance, as well as checking its entries.
    expected = ''.join(f"{row['sha256']}  {row['path']}\n" for row in freeze['artifacts'])
    expected += f"{sha(root / FREEZE)}  {FREEZE}\n{sha(root / SCRIPT)}  {SCRIPT}\n"
    require((root / MANIFEST).read_text() == expected, 'stale artifact manifest differs from freeze')
    for row in freeze['artifacts']:
        path = root / row['path']
        require(path.is_file() and sha(path) == row['sha256'] and
                path.stat().st_size == row['bytes'] and
                path.stat().st_mode & 0o777 == row['mode'], f"frozen artifact changed: {row['path']}")
    current = instrument(root) if current_instrument is None else current_instrument
    require((root / INSTRUMENT).read_text() == current, 'instrument differs from freeze')
    require(input_identity(root, current, root / 'build/memtier-nullpublish-frozen') == freeze['inputs'],
            'current build/instrument/runtime inputs differ from freeze')
    for live, frozen in (('build/tomokv', ARTIFACTS[0]), ('build/tailgen', ARTIFACTS[1])):
        require(sha(root / live) == sha(root / frozen), f'{live} differs from frozen artifact')
    return freeze


def refreeze(root, generator):
    require(not run(root, 'git', 'status', '--porcelain', '--untracked-files=normal').strip(),
            'dirty worktree; commit or remove changes before re-freezing')
    head = run(root, 'git', 'rev-parse', 'HEAD').strip()
    require(run(root, 'git', 'symbolic-ref', '--quiet', '--short', 'HEAD').strip(),
            'refreeze requires a branch')
    try:
        run(root, 'git', 'merge-base', '--is-ancestor', head, 'origin/cpp')
    except subprocess.CalledProcessError as error:
        raise ValueError('HEAD must be an ancestor of or equal to origin/cpp; land it before re-freezing') from error
    generator = generator.resolve()
    require(generator.is_file() and os.access(generator, os.X_OK), 'memtier must be an executable file')
    report = (root / REPORT).read_text()
    script = campaign(report)
    require(report.count(BEGIN) == report.count(END) == 1, 'missing/duplicate managed freeze block')
    current = instrument(root)
    inputs = input_identity(root, current, generator)
    try:
        old = check(root, current_instrument=current)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError):
        old = None
    if old and old['inputs'] == inputs:
        print(f"Already frozen on {old['source_commit']}; no build or commit needed")
        return

    build = root / 'build'
    build.mkdir(exist_ok=True)
    # Stage all artifacts before publishing any replacement. make -B prevents a
    # worktree's previous object timestamps from choosing the wrong server.
    with tempfile.TemporaryDirectory(prefix='nullpublish-refreeze-', dir=build) as temporary:
        stage = Path(temporary)
        with (build / 'nullpublish-refreeze-build.log').open('w') as log:
            subprocess.run(['taskset', '-c', '112-127', 'make', '-j16', '-B', 'build/tomokv', 'build/tailgen'],
                           cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        for source, destination in ((root / 'build/tomokv', ARTIFACTS[0]),
                                    (root / 'build/tailgen', ARTIFACTS[1]), (generator, ARTIFACTS[2])):
            shutil.copy2(source, stage / Path(destination).name)
        (stage / Path(INSTRUMENT).name).write_text(current)
        require(run(root, 'git', 'rev-parse', 'HEAD').strip() == head and
                not run(root, 'git', 'status', '--porcelain', '--untracked-files=normal').strip(),
                'worktree/HEAD changed during rebuild')
        require(input_identity(root, instrument(root), generator) == inputs,
                'inputs changed during rebuild')
        script = re.sub(r'^FROZEN_COMMIT=[0-9a-f]{40}$', 'FROZEN_COMMIT=' + head, script, flags=re.M)
        artifacts = []
        for relative in ARTIFACTS:
            path = stage / Path(relative).name if relative.startswith('build/') else root / relative
            artifacts.append(dict(path=relative, bytes=path.stat().st_size, sha256=sha(path),
                                  mode=path.stat().st_mode & 0o777))
        freeze = dict(schema=3, kind='nullpublish-build-freeze', source_commit=head,
                      inputs=inputs, artifacts=artifacts, build_cpus='112-127',
                      build_command='taskset -c 112-127 make -j16 -B build/tomokv build/tailgen', measurements_run=False,
                      campaign_arms={'A': ARTIFACTS[0], 'B': ARTIFACTS[0]})
        updated = report.replace(campaign(report), script)
        start, end = updated.index(BEGIN), updated.index(END) + len(END)
        updated = updated[:start] + frozen_block(freeze) + updated[end:]
        (stage / Path(FREEZE).name).write_text(encoded(freeze))
        (stage / Path(SCRIPT).name).write_text(script)
        manifest = ''.join(f"{row['sha256']}  {row['path']}\n" for row in artifacts)
        for relative in (FREEZE, SCRIPT):
            manifest += f"{sha(stage / Path(relative).name)}  {relative}\n"
        (stage / Path(MANIFEST).name).write_text(manifest)
        subprocess.run(['bash', '-n', str(stage / Path(SCRIPT).name)], check=True)
        for path in stage.iterdir():
            os.replace(path, build / path.name)
        (root / REPORT).write_text(updated)
    check(root, current_instrument=current)
    run(root, 'git', 'add', '--', REPORT)
    run(root, 'git', 'commit', '-m', f'refreeze on {head}')
    print(f'Refrozen on {head}; committed report, artifact hashes and campaign fence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='serverless preflight only; never rebuild or commit')
    parser.add_argument('--generate-script', action='store_true',
                        help='regenerate and syntax-check the report fence only; landed refreeze still required')
    parser.add_argument('--memtier', type=Path, default=Path(shutil.which('memtier_benchmark') or '/usr/bin/memtier_benchmark'))
    args = parser.parse_args()
    os.sched_setaffinity(0, set(range(112, 128)))
    require(not (args.check and args.generate_script), 'choose --check or --generate-script')
    if args.generate_script:
        print(generate_script(ROOT))
    elif args.check:
        check(ROOT)
        print('Frozen artifacts, inputs and report fence match')
    else:
        refreeze(ROOT, args.memtier)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'REFREEZE REFUSED: {error}', file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.output:
            print(error.output.decode(errors='replace'), file=sys.stderr)
        raise SystemExit(1)
