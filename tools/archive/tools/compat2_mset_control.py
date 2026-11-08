#!/usr/bin/env python3
"""Disposable C2 state injector: give marker-valued MSET candidates a TTL.

MSET normally clears TTL, so the requested state is not reachable by plain MSET.
This copied allocation helper creates it without changing find_notify, MVCC,
commit holding, notification delivery, or the production binary. RENAME provides
the natural production reproduction; this control covers the exact MSET shape.
"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    source, out = a.source.resolve(), a.output.resolve()
    root = Path(__file__).resolve().parents[1]
    assert out.is_relative_to(root / 'build')
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / 'src', out / 'src')
    code = out / 'src/cmd/t_string.cc'
    text = code.read_text()
    anchor = ('KvObj* xshard_make_atomic_string(Shard& shard, Slice key, Slice value,\n'
              '                                 int64_t expire_at_ms, bool integer_encode,\n'
              '                                 bool reserve_ttl_slot) {\n')
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + '''    if (value == Slice("compat2-ttl-candidate")) {
        expire_at_ms = shard.now_ms() + 700;
        std::fprintf(stderr, "compat2_mset_candidate key=%.*s deadline=%lld\\n",
                     int(key.n), key.p, (long long)expire_at_ms);
    }
''')
    code.write_text(text)
    plan = subprocess.check_output(['make', '-Bn', 'all'], cwd=source, text=True)
    commands = [shlex.split(line) for line in plan.splitlines() if line.startswith('g++ ')]
    patches, executed = {}, []
    for namespace in ('src', 'db0/src'):
        target = f'build/{namespace}/cmd/t_string.o'
        choices = [cmd for cmd in commands if '-c' in cmd and cmd[-1] == target]
        assert len(choices) == 1, target
        argv = choices[0]
        obj = out / namespace / 'cmd/t_string.o'
        obj.parent.mkdir(parents=True, exist_ok=True)
        argv[argv.index('-c') + 1] = str(code)
        argv[-1] = str(obj)
        subprocess.run(argv, cwd=source, check=True)
        patches[target] = str(obj)
        executed.append(argv)
    links = [cmd for cmd in commands if '-c' not in cmd and 'build/tomokv' in cmd]
    assert len(links) == 1
    argv = [patches.get(x, str(source / x) if x.endswith('.o') else x) for x in links[0]]
    argv[argv.index('-o') + 1] = str(out / 'tomokv')
    subprocess.run(argv, cwd=source, check=True)
    executed.append(argv)
    (out / 'commands.json').write_text(json.dumps(executed, indent=2) + '\n')


if __name__ == '__main__':
    main()
