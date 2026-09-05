#!/bin/bash
# REFUSE TO MEASURE ON A SHARED ALLOCATION.
#
# THIS LANE OWNS physical cores 58-63 and their SMT siblings 186-191, and nothing else:
#     server           58-59   (siblings 186-187 deliberately left idle)
#     load generators  60-61   plus their siblings 188-189
# and it guards only the half it uses (58-61,186-189), because another lane's server was found
# parked on 190-191 -- physical 62-63, this lane's own cores. See lib.sh.
# Re-allocated 2026-09-05. The previous pin (48-55 with load generators reaching 184-191) put this
# lane's generators on the SMT siblings of another lane's physical cores 56-63: two lanes sharing
# execution units, which is invisible in both lanes' logs and fatal to both lanes' numbers. Every
# number taken under that pin is void.
# Two rules produce the split above. A lane owns its physical cores AND their siblings (n and
# n+128), and nothing outside that set. And within the allocation, server and load generator are
# kept on DIFFERENT PHYSICAL CORES rather than on two threads of the same one, so no arm of an A/B
# is measured against a load generator sharing its execution units.
#
# This script is a refusal, not a warning. A neighbouring lane's server or load generator whose
# affinity mask touches any of our sixteen logical CPUs makes every number a two-lane measurement,
# and a two-lane measurement that nobody noticed is worse than no measurement at all.
#
#   laneguard.sh            -> exit 0 if clear, 1 and a report if not
set -u
MINE="${LANE_CPUS:-58-61,186-189}"
python3 - "$MINE" "$PPID" <<'PY'
import os, sys

def expand(spec):
    out = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out

mine = expand(sys.argv[1])
# Our own process tree is not a co-tenant with itself. Walk parents so a server this lane just
# booted is never reported as somebody else's.
def ancestors(pid):
    seen = []
    while pid and pid != 1 and len(seen) < 64:
        seen.append(pid)
        try:
            with open(f'/proc/{pid}/stat') as f:
                pid = int(f.read().rsplit(')', 1)[1].split()[1])
        except OSError:
            break
    return seen

ours = set()
for p in (os.getppid(), int(sys.argv[2])):
    ours.update(ancestors(p))

# The processes that can actually move a number: servers, load generators, replay drivers, oracles.
INTERESTING = ('memtier_benchma', 'tomokv', 'tkv-', 'replay', 'redis-server', 'valkey-server')

clashes = []
for entry in os.listdir('/proc'):
    if not entry.isdigit():
        continue
    pid = int(entry)
    try:
        with open(f'/proc/{pid}/status') as f:
            status = f.read()
    except OSError:
        continue
    name = ''
    allowed = ''
    for line in status.splitlines():
        if line.startswith('Name:'):
            name = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ''
        elif line.startswith('Cpus_allowed_list:'):
            allowed = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ''
            break
    if not name.startswith(INTERESTING):
        continue
    if pid in ours or set(ancestors(pid)) & ours:
        continue
    try:
        overlap = expand(allowed) & mine
    except ValueError:
        continue
    if overlap:
        try:
            cmd = open(f'/proc/{pid}/cmdline').read().replace('\0', ' ').strip()[:120]
        except OSError:
            cmd = name
        clashes.append((pid, name, allowed, sorted(overlap), cmd))

if clashes:
    print(f"LANEGUARD: refusing to measure -- {len(clashes)} foreign process(es) can run on "
          f"this lane's cpus ({sys.argv[1]}):")
    for pid, name, allowed, overlap, cmd in clashes:
        print(f"  pid {pid:<8} {name:<16} allowed=[{allowed}] overlap={overlap}")
        print(f"      {cmd}")
    sys.exit(1)
print(f"LANEGUARD: clear -- no foreign server or load generator can run on {sys.argv[1]}")
PY
