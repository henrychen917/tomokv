#!/usr/bin/env python3
"""Build serverless PRE, no-batch and averaged-duration falsification arms."""
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BASE = '393d6ceb129d8c99dffd70959d6a19267c525fe0'
OUT = ROOT / 'build/infofix/latency-controls'
REPORT = ROOT / 'docs/infofix'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    recipes = subprocess.check_output(['make', '-Bn', '-f', 'Makefile', '-f',
        'tools/infofix_latency.mk', 'build/infofix-latency-unit'], cwd=ROOT, text=True)
    commands = [shlex.split(line) for line in recipes.splitlines() if line.startswith('g++ ')]
    compile_template, = [c for c in commands if '-c' in c and 'tests/infofix_latency_unit.cc' in c]
    link_template, = [c for c in commands if '-c' not in c and '-o' in c and
                     c[c.index('-o') + 1] == 'build/infofix-latency-unit']
    archive = subprocess.check_output(['git', 'archive', BASE, 'src'], cwd=ROOT)
    pre_source = OUT / 'pre/source'
    pre_source.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(pre_source, filter='data')
    source = (ROOT / 'src/cmd/latency_tracking.cc').read_text()
    reports = []
    for arm in ('pre', 'no-batch', 'average', 'empty-entry'):
        destination = OUT / arm
        destination.mkdir(parents=True, exist_ok=True)
        include = pre_source if arm == 'pre' else destination / 'source'
        if arm != 'pre':
            if arm == 'no-batch':
                changed = source.replace('bool get_batch = n > 1;', 'bool get_batch = false;', 1)
            elif arm == 'average':
                changed = source.replace('batch->histogram->add((duration_ns / 1000) * 1000);',
                    'batch->histogram->add(8000000); // planted shared-duration regression', 1)
            else:
                changed = source.replace('if (histogram.calls) result[id].merge(histogram);',
                    'result[id].merge(histogram); // planted empty-entry regression', 1)
            assert changed != source
            file = include / 'src/cmd/latency_tracking.cc'
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(changed)
        compile = list(compile_template)
        at = compile.index('-I.')
        compile[at:at] = ['-I' + str(include), '-Isrc/cmd']
        if arm == 'pre': compile += ['-DTOMO_INFOFIX_BASELINE']
        compile[compile.index('-o') + 1] = str(destination / 'unit.o')
        link = [str(destination / 'unit.o') if x == 'build/infofix-latency-unit.o' else
                str(ROOT / 'build/infofix/pre' / x.removeprefix('build/'))
                if arm == 'pre' and x.endswith('.o') and x.startswith(('build/src/', 'build/third_party/')) else x
                for x in link_template]
        binary = destination / 'unit'
        link[link.index('-o') + 1] = str(binary)
        with (destination / 'build.log').open('w') as log:
            subprocess.run(compile, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
            subprocess.run(link, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
        reports.append(dict(arm=arm, binary=str(binary.relative_to(ROOT)),
            sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), compile=compile, link=link))
    (REPORT / 'latency-controls.json').write_text(json.dumps(reports, indent=2) + '\n')


if __name__ == '__main__':
    main()
