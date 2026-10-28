#!/usr/bin/env python3
"""Build reviewable throwaway regressions and a PRE behavior/layout PAD input."""
import argparse, hashlib, json, os, shutil, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/streamfix'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def replace(path, before, after, changes):
    text = path.read_text()
    assert text.count(before) == 1, (path, before, text.count(before))
    path.write_text(text.replace(before, after, 1))
    changes.append(dict(file=str(path), before=before, after=after))


def build(kind):
    source = BASE / (kind + '-source')
    objects = BASE / (kind + '-objects')
    assert not source.exists() and not objects.exists(), 'Preserve existing controls; use a new name after changes'
    source.mkdir();objects.mkdir()
    original = BASE / 'pre-source' if kind == 'pad-layout' else ROOT
    for name in ('src', 'third_party', 'tools'):
        shutil.copytree(original/name, source/name)
    shutil.copy2(original/'Makefile', source/'Makefile')
    changes = []
    if kind == 'pad-layout':
        replace(source/'src/store/typeval.h', '    uint32_t physical_entries = 0;\n};\n\nstruct StreamNodeIndex',
                '    uint32_t physical_entries = 0;\n    uint32_t deleted_entries = 0;\n    uint64_t wire_bytes = 0;\n};\n\nstruct StreamNodeIndex', changes)
    else:
        # Seed immutable release objects, then explicitly discard every affected TU in both
        # namespaces. Copied .d files name the original build root, so do not trust them here.
        for name in ('src', 'db0', 'third_party'):
            subprocess.run(['cp', '-a', '--reflink=auto', str(ROOT/'build'/name), str(objects/name)], check=True)
        for p in source.rglob('*'):
            if p.is_file(): os.utime(p, (1,1))
        stream = source/'src/cmd/t_stream.cc'
        replace(stream, "latest = input.n == 1 && (input.p[0] == '$' || input.p[0] == '+');",
                "latest = input.n == 1 && input.p[0] == '$';", changes)
        replace(stream, 'parse_id_numeric(input, id, start ? 0 : UINT64_MAX, !exclusive)',
                'parse_id_numeric(input, id, start ? 0 : UINT64_MAX, true)', changes)
        replace(stream, 'if (trim.limit && node_live > trim.limit) return {};',
                'if (false && trim.limit && node_live > trim.limit) return {};', changes)
        replace(stream, '    if (trim.approximate) return {};',
                '    if (false && trim.approximate) return {};', changes)
        groups = source/'src/cmd/t_stream_groups.cc'
        replace(groups, 'else if (!parse_id(op.arg(4), id, 0, true))',
                'else if (!parse_id(op.arg(4), id))', changes)
        replace(groups, 'if (!parse_id(op.arg(5), start, 0, true))',
                'if (!parse_id(op.arg(5), start))', changes)
        replace(groups, 'static_cast<uint64_t>(parsed) > uint64_t{INT64_MAX} / sizeof(StreamID)',
                '(false && static_cast<uint64_t>(parsed) > uint64_t{INT64_MAX} / sizeof(StreamID))', changes)
        replace(source/'src/cmd/xshard_commands.inc',
                'if (!parse_i64(op.arg(++i), parsed_count) || parsed_count < 1) {\n            reply_err(op.sink(), "ERR count should be greater than 0");',
                'if (!parse_i64(op.arg(++i), parsed_count) || parsed_count < 1) {\n            reply_err(op.sink(), "ERR value is not an integer or out of range");', changes)
        block = source/'src/cmd/blocking.inc'
        replace(block, 'if (!parse_i64(input, parsed) || parsed < 1) {\n        reply_err(op.sink(), "ERR count should be greater than 0");',
                'if (!parse_i64(input, parsed) || parsed < 1) {\n        reply_err(op.sink(), "ERR value is not an integer or out of range");', changes)
        replace(block, 'if (!parse_i64(op.arg(2), parsed_keys) || parsed_keys < 1) {\n                reply_err(op.sink(), "ERR numkeys should be greater than 0");',
                'if (!parse_i64(op.arg(2), parsed_keys) || parsed_keys < 1) {\n                reply_err(op.sink(), "ERR value is not an integer or out of range");', changes)
        for prefix in ('src', 'db0/src'):
            for unit in ('t_stream', 't_stream_groups', 'xshard'):
                (objects/prefix/'cmd'/(unit+'.o')).unlink()
    command = ['make', '-j16', 'BUILD_ROOT='+str(objects), 'all']
    receipt = dict(kind=kind, changes=changes, command=command, affinity=sorted(os.sched_getaffinity(0)))
    log = ROOT/'docs/streamfix'/(kind+'-build.log')
    with log.open('w') as f:
        result = subprocess.run(command, cwd=source, stdout=f, stderr=subprocess.STDOUT)
    receipt['exit'] = result.returncode
    if result.returncode == 0:
        receipt['binary'] = str(objects/'tomokv');receipt['sha256'] = sha(objects/'tomokv')
    (ROOT/'docs/streamfix'/(kind+'-build.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    assert result.returncode == 0, log


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('kind', choices=('mutant','pad-layout'))
    build(p.parse_args().kind)
