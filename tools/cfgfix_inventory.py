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
        return 'Runtime ON starts an unpublished increment and initial rewrite; OFF drains, fsyncs and closes. Outstanding: switches refuse active atomic/snapshot/topology work instead of Redis cancellation/scheduling.'
    if name == 'aof-use-rdb-preamble':
        return 'Native AOF bases are TomoKV snapshots: yes is accepted, no is rejected explicitly. This format boundary now blocks stream-cgroups after appendonly setup succeeds.'
    if name == 'bind':
        return 'Runtime rebind implemented; IPv4 single address remains the transport boundary (Redis also accepts lists/IPv6/optional addresses).'
    if name in {'dir', 'dbfilename', 'enable-protected-configs'}:
        return 'UNFIXED: persistence paths are retained at boot; protected-config policy is not implemented.'
    if name.startswith('tls-') and name != 'tls-auth-clients':
        return 'TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented.'
    if name in {'hll-sparse-max-bytes', 'tracking-table-max-keys'}:
        return 'UNFIXED: captured in boot-owned HLL/tracking structures; no live migration is implemented.'
    if not present and (name.startswith(('rdb', 'aof-')) or name in {'no-appendfsync-on-rewrite', 'stop-writes-on-bgsave-error'}):
        return 'Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented.'
    if name.startswith(('active-defrag', 'activedefrag', 'lazyfree-', 'activerehashing')):
        return 'FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller.'
    if name in {'io-threads', 'io-threads-do-reads', 'server-cpulist', 'server_cpulist', 'bio-cpulist', 'bio_cpulist',
        'aof-rewrite-cpulist', 'aof_rewrite_cpulist', 'bgsave-cpulist', 'bgsave_cpulist'}:
        return 'TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools.'
    reasons = {
        'always-show-logo': 'Startup has a TomoKV banner, with no Redis-style conditional logo renderer.',
        'set-proc-title': 'Worker names and the original argv remain intact; no process-title storage or renderer exists.',
        'proc-title-template': 'No process-title storage/renderer or Redis title substitution grammar exists.',
        'jemalloc-bg-thread': 'jemalloc policy is inherited from the allocator; its mallctl background-thread switch is not exposed.',
        'crash-log-enabled': 'Native assert-map/core-dump diagnostics have no Redis crash-report signal handler to toggle.',
        'crash-memcheck-enabled': 'No crash-time memory checker exists for concurrently owned/QSBR-retired stores.',
        'use-exit-on-panic': 'Native assertion failures abort; no configurable panic exit policy exists.',
        'disable-thp': 'Boot does not expose PR_SET_THP_DISABLE; this process setting still requires implementation.',
        'hide-user-data-from-log': 'Existing diagnostics lack the data-classification metadata needed for a complete redaction policy.',
        'ignore-warnings': 'Boot diagnostics have no named warning registry or suppression parser.',
        'oom-score-adj': 'The Linux OOM adjustment apply/restore mechanism has not been implemented.',
        'oom-score-adj-values': 'No configurable OOM-score policy for process roles exists; native persistence uses owner threads, not Redis fork children.',
        'socket-mark-id': 'Listener creation does not apply SO_MARK; the immutable socket option remains absent.',
        'watchdog-period': 'No Redis-style watchdog signal/timer exists; native worker stall diagnostics use other mechanisms.',
        'shutdown-timeout': 'Redis waits for replica catch-up here; TomoKV has no replicas and uses its own final-save/drain deadlines.',
        'list-compress-depth': 'Native compact/quicklist storage has no Redis LZF interior-node compression; accepting this would be ineffective.',
        'lfu-log-factor': 'Native LFU admission/counter code uses fixed policy constants, without a live logarithmic-factor control.',
        'lfu-decay-time': 'Native LFU decay uses its existing clock policy, without Redis minute-based live reconfiguration.',
        'maxmemory-eviction-tenacity': 'Owner-local eviction has a different bounded work budget; no Redis tenacity mapping has been implemented.',
        'active-expire-effort': 'Expiry uses owner-local incremental budgets; the Redis effort-to-budget mapping is absent.',
        'maxmemory-clients': 'Client accounting exists, but Redis client-memory eviction and percentage limits are absent.',
        'max-new-connections-per-cycle': 'Accept batching/multishot io_uring admission has no Redis per-cycle quota setting.',
        'max-new-tls-connections-per-cycle': 'TLS accept admission has no Redis per-cycle quota setting.',
        'loading-process-events-interval-bytes': 'Native loading is coordinated across owners; Redis single-thread event-pump byte intervals have no mapping.',
        'busy-reply-threshold': 'Script execution has native instruction/work budgets, without Redis elapsed-time busy-reply policy.',
        'lua-time-limit': 'Alias of busy-reply-threshold; native instruction/work budgets do not implement its elapsed-time policy.',
        'lua-enable-deprecated-api': 'Lua API registration does not expose Redis deprecated-API gating.',
        'sanitize-dump-payload': 'DUMP/RESTORE uses native checksummed object images; Redis RDB sanitization policy does not apply.',
    }
    if not present:
        return 'UNFIXED: ' + reasons.get(name, 'No corresponding implementation; rejected rather than accepted without effect.')
    if name == 'latency-tracking':
        return 'Default remains no (Redis yes): optional histogram observers are off in the measured baseline; changing this default requires a separately measured cost decision.'

    if name in {'port', 'maxclients', 'save', 'protected-mode', 'enable-debug-command'}:
        return 'Captured value includes the gate harness override; boot default comparison needs the source defaults.'
    return 'Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation.'

default_overrides = {'port': True, 'bind': False, 'dir': True, 'maxclients': True, 'save': True, 'appendonly': True, 'protected-mode': True, 'enable-debug-command': True}
lines = ['# Redis 7.4.10 configuration inventory', '',
    'Source: `/home/user/Projects/redis/src/config.c`, `standardConfig static_configs[]`. '
    'Every canonical row and alias is included, including conditional and hidden rows. '
    'Since is the first source spelling in history through PRE (parser or CONFIG registration); '
    '`cfgfix` means newly introduced here. Replies are explicit-name GET receipts from the gate job. '
    'Overridden defaults are compared from Config initializers and Redis initServerConfig/standardConfig: port 6379, maxclients 10000, save 3600/1 300/100 60/10000, appendonly no, protected-mode yes, debug no, dir current directory; bind differs (127.0.0.1 versus * -::*). '
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
        default = ('yes' if default_overrides[name] else 'no') + ' (source defaults)' if name in default_overrides else ('yes' if equal else 'no' if old else 'oracle absent')
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
