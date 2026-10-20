"""Exhaustive interleaving model of Server::atomic_commit_reserve/atomic_commit_publish
(src/core/server.h:2566-2586) for N single-ticket committers.

Committer steps (current code):
  R1 inflight.fetch_add(1)            R2 t = commit_seq.fetch_add(1)+1
  S  epoch[t] = stored                L  drawn = commit_seq.load()
  D  old = inflight.fetch_sub(1); if old != 1 -> done (atomic_commit_windows++)
  P  safe = max(safe, drawn) -> done
Fixed variant adds, after P (last decrementer only):
  F1 s = commit_seq.load(); if s <= safe -> done
  F2 if inflight.load() != 0 -> done
  F3 safe = max(safe, s) -> goto F1
Safety : every ticket <= safe has its epoch stored (no reader cut names an undecided ticket).
Liveness at quiescence: when every committer is done, safe == commit_seq.
"""

def run(n, fixed, exact=False):
    init = ((0, 0, 0, 0),) * n          # per committer: (pc, ticket, drawn, s)
    start = (init, (0, 0, 0, 0))        # global: (inflight, seq, safe, stored_bits)
    seen, stack = set(), [(start, ())]
    bad_safety = bad_live = 0
    examples, finals = [], set()
    while stack:
        (locs, g), trace = stack.pop()
        if (locs, g) in seen:
            continue
        seen.add((locs, g))
        inflight, seq, safe, stored = g
        if any(not (stored >> t) & 1 for t in range(1, safe + 1)):
            bad_safety += 1
            examples.append(('SAFETY', trace))
        if all(l[0] == 'done' for l in locs):
            finals.add(g)
            if safe != seq:
                bad_live += 1
                examples.append((f'ORPHAN safe={safe} seq={seq}', trace))
            continue
        for i, (pc, t, drawn, s) in enumerate(locs):
            if pc == 'done':
                continue
            nl, ng = list(locs), [inflight, seq, safe, stored]
            if pc == 0:   ng[0] += 1; nl[i] = (1, t, drawn, s); step = f'C{i}:inflight++'
            elif pc == 1: ng[1] += 1; nl[i] = (2, ng[1], drawn, s); step = f'C{i}:draw t={ng[1]}'
            elif pc == 2: ng[3] |= 1 << t; nl[i] = (3, t, drawn, s); step = f'C{i}:store epoch[{t}]'
            elif pc == 3: nl[i] = (4, t, seq, s); step = f'C{i}:drawn=seq({seq})'
            elif pc == 4:
                old = ng[0]; ng[0] -= 1
                nl[i] = ('done', t, drawn, s) if old != 1 else (5, t, drawn, s)
                step = f'C{i}:inflight-- (was {old})'
            elif pc == 5:
                ng[2] = max(ng[2], drawn)
                nl[i] = (6, t, drawn, s) if fixed else ('done', t, drawn, s)
                step = f'C{i}:safe=max(safe,{drawn})'
            elif pc == 6:
                nl[i] = ('done', t, drawn, seq) if seq <= (drawn if exact else safe) else (7, t, drawn, seq)
                step = f'C{i}:recheck seq={seq}'
            elif pc == 7:
                nl[i] = ('done', t, drawn, s) if inflight != 0 else (8, t, drawn, s)
                step = f'C{i}:inflight={inflight}'
            elif pc == 8:
                ng[2] = max(ng[2], s); nl[i] = (6, t, s if exact else drawn, s); step = f'C{i}:safe=max(safe,{s})'
            stack.append(((tuple(nl), tuple(ng)), trace + (step,)))
    return len(seen), bad_safety, bad_live, examples, finals

for fixed in (False, True):
    for n in (2, 3):
        states, bs, bl, ex, finals = run(n, fixed)
        print(f"{'FIXED' if fixed else 'CURRENT'} committers={n}: states={states} "
              f"safety_violations={bs} orphaned_final_states={bl} "
              f"final(safe,seq)={sorted({(f[2], f[1]) for f in finals})}")
        if not fixed and n == 2 and ex:
            print('  example', ex[0][0]); [print('    ', s) for s in ex[0][1]]
        assert bs == 0
        assert bl == (0 if fixed else {2: 2, 3: 36}[n]), 'lost the required liveness witness'

# Appendix A compares newer with shared safe. Also enumerate the literal 5.1
# implementation: compare with local drawn, then adopt newer on the back edge.
for n in (2, 3):
    states, bs, bl, ex, finals = run(n, True, exact=True)
    print(f'EXACT FIX committers={n}: states={states} safety_violations={bs} '
          f'orphaned_final_states={bl}')
    assert bs == bl == 0
