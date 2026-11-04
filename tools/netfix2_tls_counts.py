#!/usr/bin/env python3
"""20KB TLS GET owner scopes, clean and WATCHed, with exact replies on both arms.

Builds an auditable derivative of the existing serverless scope. OpenSSL/socket
work and library memcpy internals are outside this named-production scope.
"""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import netfix2_counts as base

scope = base.scope
ROOT = base.ROOT


def main():
    assert os.sched_getaffinity(0) <= set(range(8, 16))
    source_text = (ROOT / 'tests/wave11_scope.cc').read_text()
    text = source_text.replace('using namespace tomo;', 'using namespace tomo;\nbool tls_scope_watch = false;', 1)
    text = text.replace('command_registry_init(false)', 'command_registry_init(true)')
    text = text.replace("std::string(64,'v')", "std::string(20000,'v')")
    text = text.replace('   Task tasks[32];need(n<=32);',
        '   if(tls_scope_watch)need(server.shard(0).watch_add(Slice(keys[0]), &client, client.watch_generation()));\n'
        '   need(server.shard(0).has_watches() == tls_scope_watch);\n'
        '   Task tasks[32];need(n<=32);')
    text = text.replace('op->spec=command_lookup(op->arg(0));op->hash=',
                        'op->spec=command_tls_variant(command_lookup(op->arg(0)));op->hash=')
    text = text.replace('"$64\\r\\n"+value+"\\r\\n"', '"$20000\\r\\n"+value+"\\r\\n"')
    text = text.replace('    need(std::string(op.reply.data(),op.reply.size()) == expected);',
        '    std::string actual(op.reply.data(),op.reply.size());\n'
        '    if(op.zc_ptr){actual.append(op.zc_ptr,op.zc_len);actual+="\\r\\n";server.shard(0).store().unborrow(op.zc_ptr);}\n'
        '    need(actual == expected);')
    text = text.replace(' if(argc!=6)return 2;',
                        ' if(argc!=6)return 2;\n tls_scope_watch=std::string(argv[1])=="TLSGET-watch";')
    text = text.replace('::run<true>(argv[1],', '::run<true>("GET",')
    text = text.replace('::run<false>(argv[1],', '::run<false>("GET",')
    fixture = ROOT / 'build/netfix2/tls_scope.cc'
    fixture.write_text(text)
    rows = []
    for arm in ('PRE', 'POST'):
        source, objects = ((ROOT / 'build/netfix2/pre-source', ROOT / 'build/netfix2')
                           if arm == 'PRE' else (ROOT, ROOT / 'build'))
        for ns in ('normal', 'db0'):
            binary = scope.build(arm + '-TLS', source, objects, ns, str(fixture))
            prepared = scope.prepare(binary, objects, ns, 'complete')
            cases = [(cmd, mode, batch, 1) for cmd in ('TLSGET', 'TLSGET-watch')
                     for mode in ('1s', '2s') for batch in (1, 32)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                rows += list(pool.map(lambda c: scope.trace(prepared, arm + '-TLS', ns, 'complete', *c), cases))
    scope.save(scope.DOC / 'tls-results.json', rows)
    keys = ('namespace', 'command', 'mode', 'batch', 'atomic')
    old = {tuple(r[k] for k in keys): r for r in rows if r['arm'] == 'PRE-TLS'}
    pairs = [dict(**{k: r[k] for k in keys}, pre=old[tuple(r[k] for k in keys)]['total'],
                  post=r['total'], delta=r['total']-old[tuple(r[k] for k in keys)]['total'])
             for r in rows if r['arm'] == 'POST-TLS']
    scope.save(scope.DOC / 'tls-comparison.json', pairs)
    print(pairs)


if __name__ == '__main__':
    main()
