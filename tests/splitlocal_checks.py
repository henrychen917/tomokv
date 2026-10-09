#!/usr/bin/env python3
"""Source-bound template witness for WB4/IO5 and IO1; never starts a server.

Compile the real call arguments/defaults/policy expressions with a consteval
recorder. This proves template selection, not TLS callback reachability.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

import r7shadow_sync as sync

ROOT = Path(__file__).resolve().parents[1]


def method(source, name):
    # Normalize the generated member definitions for the same anchored extractor.
    if name.startswith('r7_'):
        source = source.replace('IoLoop::DispatchResult IoLoop::', 'DispatchResult ')
        source = re.sub(r'^(uint32_t|void|bool) IoLoop::', r'\1 ', source, flags=re.M)
        source = '\n'.join('    ' + line for line in source.splitlines())
    return sync.function(source, name)


def emit(root, output):
    code = ['#include <cstdint>\n#include <cstdio>\n'
            'constexpr uint32_t kGenthreadIfidBatchOps = 32;\n'
            'struct Policy { bool borrow; uint32_t batch; bool local, fused, build, discard; };']
    header = (root / 'src/core/genthread_pipeline.h').read_text()
    quantum = re.search(r'kGenthreadIfidBatchOps\s*=\s*([^;]+);', header)
    assert quantum, 'IFID quantum inventory'
    code[0] = code[0].replace('= 32;', '= ' + quantum[1] + ';')
    for filename, prefix in [('src/core/io_loop.h', ''), ('src/core/reorder.cc', 'r7_')]:
        source = (root / filename).read_text()
        parser = method(source, prefix + 'parse_and_dispatch')
        defaults = parser[:parser.index('DispatchResult')].strip()
        formula = re.search(r'static constexpr bool Fused = ([\s\S]*?);', parser)
        guards = re.findall(r'if constexpr \((Fused && !SplitLocal)\)', parser)
        assert formula and len(guards) == 2, 'prebuild/discard policy inventory'
        assert 'srv_->thread_mode() == ThreadMode::Fused)' in parser, 'prebuild runtime mode gate'
        code.append('namespace ' + ('r7' if prefix else 'fifo') + ' {\n' + defaults +
                    '\nconstexpr Policy ' + prefix + 'parse_and_dispatch(void*) {\n'
                    'constexpr bool Fused = ' + formula[1] + ';\n'
                    'return {NoBorrow, BatchOps, SplitLocal, Fused, ' +
                    guards[0] + ', ' + guards[1] + '};\n}')
        for name in ('flush_ready',):
            body = method(source, prefix + name)
            calls = re.findall(r'\b' + prefix + r'parse_and_dispatch<[^>]+>\(c\)', body)
            assert len(calls) == 6, (name, 'six TLS/plain/pause parse sites')
            code.append('template<bool Fused, bool SplitLocal> consteval bool ' + name + '() {\n'
                        'void* c = nullptr;\nconstexpr bool no_borrow[] = {true,false,false,true,false,false};\n'
                        'const Policy sites[] = {' + ',\n'.join(calls) + '};\n'
                        'for (unsigned i=0; i<6; ++i) { const auto p=sites[i];\n'
                        'if (p.local != SplitLocal || p.fused != Fused || p.borrow != no_borrow[i] ||\n'
                        'p.batch != (Fused ? kGenthreadIfidBatchOps : 0) ||\n'
                        'p.build != (Fused && !SplitLocal) || p.discard != p.build) return false;\n'
                        '} return true; }')
            modes = [(False, False), (True, False), (True, True)]
            for fused, local in modes:
                code.append('static_assert(' + name + '<' + str(fused).lower() + ',' + str(local).lower() +
                            '>(), "' + ('r7: ' if prefix else 'fifo: ') + name + ' preserves SplitLocal and prebuild policy");')
        loop = method(source, prefix + 'run_loop')
        polls = re.findall(r'\b' + prefix + r'epoll_pass<([^>]+)>\((0|Ring::kWaitTimeoutMs)\)', loop)
        assert len(polls) == 3 and [p[1] for p in polls] == ['0', 'Ring::kWaitTimeoutMs', 'Ring::kWaitTimeoutMs'], 'epoll callback inventory'
        code.append('template<bool U, bool T, bool F> consteval bool ' + prefix +
                    'epoll_pass(int) { return F; }\n'
                    'template<bool HasUnix, bool HasTls, bool Fused, bool SplitLocal>\n'
                    'consteval bool park() {\n'
                    'constexpr bool hot = ' + prefix + 'epoll_pass<' + polls[0][0] + '>(0);\n'
                    'if constexpr (Fused) return hot == ' + prefix + 'epoll_pass<' + polls[1][0] + '>(50);\n'
                    'else return hot == ' + prefix + 'epoll_pass<' + polls[2][0] + '>(50);\n}')
        for unix in ('false', 'true'):
            for tls in ('false', 'true'):
                for fused, local in [('false','false'), ('true','false'), ('true','true')]:
                    code.append(f'static_assert(park<{unix},{tls},{fused},{local}>(), '
                                '"' + ('r7: ' if prefix else 'fifo: ') + 'park/hot callback Fused policy mismatch");')
        code.append('}')
    code.append('int main() { std::puts("PASS splitlocal: FIFO/R7 forwarding, prebuild/discard, park policies"); }')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(code) + '\n')


def check(binary, output):
    subprocess.run([str(binary.resolve())], check=True)
    subprocess.run(['python3', 'tests/r7shadow_sync.py'], cwd=ROOT, check=True)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    # Throwaway source overlays: no production file or production binary is changed.
    for name, old, new, marker in [
        ('old-forwarding', 'Fused ? kGenthreadIfidBatchOps : 0, SplitLocal',
         'Fused ? kGenthreadIfidBatchOps : 0', 'flush_ready preserves SplitLocal and prebuild policy'),
        ('old-park', 'epoll_pass<HasUnix, HasTls, Fused>(Ring::kWaitTimeoutMs)',
         'epoll_pass<HasUnix, HasTls, !SplitLocal, Pipeline>(Ring::kWaitTimeoutMs)', 'park/hot callback Fused policy mismatch')]:
        dest = output / name
        for relative in ('src/core/io_loop.h', 'src/core/reorder.cc', 'src/core/genthread_pipeline.h'):
            text = (ROOT / relative).read_text()
            if relative.endswith(('io_loop.h', 'reorder.cc')):
                count = 6 if name == 'old-forwarding' else 1
                assert text.count(old) == count, (name, relative, text.count(old))
                text = text.replace(old, new)
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        unit = dest / 'unit.cc'
        emit(dest, unit)
        makefile = dest / 'Makefile'
        makefile.write_text('unit: unit.cc\n\t$(CXX) -std=c++20 -O2 -Wall -Wextra unit.cc -o unit\n')
        result = subprocess.run(['taskset', '-c', '112-127', 'make', '-j16', '-C', str(dest.resolve())],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (dest / 'compile.log').write_text(result.stdout)
        assert result.returncode != 0 and marker in result.stdout, (name, result.stdout)
        # Both authoritative and generated expressions must reject the old argument.
        assert 'fifo: ' + marker in result.stdout and 'r7: ' + marker in result.stdout, result.stdout
        rows.append(dict(control=name, exit=result.returncode, assertion=marker, rejected=True))
        print('PASS negative control:', name, 'rejected at', marker)
    (output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    e = sub.add_parser('emit'); e.add_argument('output', type=Path)
    e.add_argument('--root', type=Path, default=ROOT)
    c = sub.add_parser('check'); c.add_argument('--binary', type=Path, default=ROOT / 'build/splitlocal-unit')
    c.add_argument('--output', type=Path, default=ROOT / 'build/splitlocal/controls')
    args = p.parse_args()
    if args.action == 'emit': emit(args.root, args.output)
    else: check(args.binary, args.output)
