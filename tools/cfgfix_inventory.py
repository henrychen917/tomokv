#!/usr/bin/env python3
"""Inventory the local Redis standardConfig table and captured CONFIG replies."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from serverfix_config import IMMUTABLE

parser = argparse.ArgumentParser()
parser.add_argument('proof', type=Path)
args = parser.parse_args()
source = Path('/home/user/Projects/redis/src/config.c').read_text()
table = source.split('standardConfig static_configs[] = {')[1].split('/* NULL Terminator')[0]
oracle = json.loads((args.proof / 'oracle.explicit.json').read_text())
candidate = json.loads(next(args.proof.glob('candidate-*.explicit.json')).read_text())
pre = json.loads((ROOT / 'docs/cfgfix/pre/oracle.configs.json').read_text()) if (ROOT / 'docs/cfgfix/pre/oracle.configs.json').exists() else {}
history = subprocess.check_output(['git', 'log', '--reverse', '--format=COMMIT:%h', '-p',
    '105c5818c', '--', 'src/core/config.h', 'src/cmd/t_server.cc'], text=True)
since, commit = {}, ''
for line in history.splitlines():
    if line.startswith('COMMIT:'): commit = line[7:]
    if line.startswith('+') and not line.startswith('+++'):
        for name in re.findall(r'"(?:--)?([a-z][a-z0-9-]+)"', line): since.setdefault(name, commit)

def reason(name, present):
    if name.startswith(('cluster-', 'repl-', 'replica-', 'slave-', 'min-replicas-', 'min-slaves-')) or name in {
        'replicaof', 'slaveof', 'masterauth', 'masteruser', 'tls-cluster', 'tls-replication',
        'enable-module-command', 'bind-source-addr', 'propagation-error-behavior'}:
        return 'Excluded surface: cluster, replication, or modules; no corresponding service.'
    if name in {'req-res-logfile', 'client-default-resp'}:
        return 'Redis LOG_REQ_RES conditional build setting; absent in the supplied oracle.'
    if name == 'appendonly':
        return 'UNFIXED: runtime activation requires a persistence cut, producer/writer rebinding and durable stop; currently boot-only.'
    if name == 'bind':
        return 'Runtime rebind implemented; IPv4 single address remains the transport boundary (Redis also accepts lists/IPv6/optional addresses).'
    if name in {'dir', 'dbfilename', 'enable-protected-configs'}:
        return 'UNFIXED: persistence paths are retained at boot; protected-config policy is not implemented.'
    if name.startswith('tls-') and name != 'tls-auth-clients':
        return 'TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented.'
    if name in {'hll-sparse-max-bytes', 'tracking-table-max-keys'}:
        return 'UNFIXED: captured in boot-owned HLL/tracking structures; no live migration is implemented.'
    if name.startswith(('rdb', 'aof-')) or name in {'no-appendfsync-on-rewrite', 'stop-writes-on-bgsave-error'}:
        return 'Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented.'
    if name.startswith(('active-defrag', 'activedefrag', 'lazyfree-', 'activerehashing')):
        return 'FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller.'
    if name in {'io-threads', 'io-threads-do-reads', 'server-cpulist', 'server_cpulist', 'bio-cpulist', 'bio_cpulist',
        'aof-rewrite-cpulist', 'aof_rewrite_cpulist', 'bgsave-cpulist', 'bgsave_cpulist'}:
        return 'TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools.'
    if not present:
        return 'UNFIXED: no implementation for this Redis control; it is rejected, never accepted as an ineffective setting.'
    if name in {'port', 'maxclients', 'save', 'protected-mode', 'enable-debug-command'}:
        return 'Captured value includes the gate harness override; boot default comparison needs the source defaults.'
    return 'Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation.'

overridden = {'port', 'bind', 'dir', 'maxclients', 'save', 'appendonly', 'protected-mode', 'enable-debug-command'}
lines = ['# Redis 7.4.10 configuration inventory', '',
    'Source: `/home/user/Projects/redis/src/config.c`, `standardConfig static_configs[]`. '
    'Every canonical row and alias is included, including conditional and hidden rows. '
    'Since is the first source spelling in history through PRE (parser or CONFIG registration); '
    '`cfgfix` means newly introduced here. Replies are explicit-name GET receipts from the gate job. '
    'Default equality is not inferred for settings overridden by the harness. '
    'A documented UNFIXED row is an outstanding requirement, not a claim of Redis parity.', '',
    '| Redis name | Present / since | Mutable Redis / Tomo | Default equal | CONFIG GET equal | Hidden / protected equal | Difference or reason |',
    '|---|---|---|---|---|---|---|']
records=[]
for match in re.finditer(r'create\w+Config\("([^"]+)", (NULL|"[^"]+"), ([^,]+),', table):
    canonical, alias, flags = match.groups()
    for name in [canonical] + ([] if alias == 'NULL' else [alias.strip('"')]):
        old, new = oracle.get(name, []), candidate.get(name, [])
        present = bool(new)
        redis_mutable = 'IMMUTABLE_CONFIG' not in flags
        tomo_mutable = present and canonical not in IMMUTABLE
        equal = old == new if old else None
        hidden = 'HIDDEN_CONFIG' in flags
        protected = 'PROTECTED_CONFIG' in flags
        tomo_hidden = name == 'key-load-delay'
        tomo_protected = name in {'dir', 'dbfilename'}
        flag_equal = present and hidden == tomo_hidden and protected == tomo_protected
        default = 'NOT MEASURED (override)' if name in overridden else ('yes' if equal else 'no')
        row = dict(name=name, canonical=canonical, redis_flags=flags, present=present,
                   since=since.get(name, 'cfgfix') if present else None,
                   mutable_redis=redis_mutable, mutable_tomo=tomo_mutable if present else None,
                   default_equal=default, get_equal=equal, oracle=old, candidate=new,
                   flags_equal=flag_equal, reason=reason(canonical,present))
        records.append(row)
        lines.append(f'| `{name}` | '+('yes / '+row['since'] if present else 'no')+
            f' | {"yes" if redis_mutable else "no"} / '+('yes' if tomo_mutable else 'no' if present else '—')+
            f' | {default} | '+('yes' if equal else 'no' if old else 'oracle absent')+
            f' | {"yes" if flag_equal else "no"} (Redis {int(hidden)}/{int(protected)}) | {row["reason"]} |')
out=ROOT/'docs/cfgfix'
(out/'inventory.md').write_text('\n'.join(lines)+'\n')
(out/'inventory.json').write_text(json.dumps(records,indent=2)+'\n')
print(f'{len(records)} canonical/alias rows; {sum(r["present"] for r in records)} present')
