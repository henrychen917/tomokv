#!/usr/bin/env python3
"""trial_lib compile + (a) hot bodies changed, (b) collateral count, (c) parse_and_dispatch bodies whose
non-fingerprint call-target multiset differs from PRE (signed deltas). Usage: trialcalls.py <obj> '<params>'..."""
import collections, concurrent.futures as cf, json, os, re, subprocess, sys
os.environ['TRIAL_OBJ'] = sys.argv[1]
sys.path.insert(0, '/home/user/Projects/cx-flipfix/build/flipfix')
import trial_lib as T
def calls(obj):
    out = subprocess.check_output(['objdump', '-dr', '--no-show-raw-insn', '-C', str(obj)], text=True)
    bodies, cur = {}, None
    for line in out.splitlines():
        m = re.match(r'^[0-9a-f]+ <(.*)>:$', line)
        if m:
            cur = m[1] if 'parse_and_dispatch' in m[1] else None
            if cur: bodies[cur] = collections.Counter()
            continue
        if cur and 'R_X86_64_PLT32' in line:
            t = line.split('R_X86_64_PLT32', 1)[1].strip()
            if re.search(r'publish_sampled_pass|flip_fingerprint_note', t): continue
            bodies[cur][t] += 1
    return bodies
pre_calls = calls(T.WT / 'build/flipfix/pre' / T.obj)
with cf.ThreadPoolExecutor(int(os.environ.get('JOBS', '6'))) as pool:
    for params, path in pool.map(T.compile_with, sys.argv[2:]):
        counts, collateral = T.classify(path)
        post_calls = calls(path)
        bad = {}
        for name in sorted(set(pre_calls) | set(post_calls)):
            a, b = pre_calls.get(name, collections.Counter()), post_calls.get(name, collections.Counter())
            d = {k.replace('-0x4', ''): b[k] - a[k] for k in set(a) | set(b) if a[k] != b[k]}
            if d: bad[name] = d
        print(json.dumps({'params': params.split('=')[-1], 'call_diff_bodies': len(bad),
                          'call_delta_abs': sum(abs(v) for d in bad.values() for v in d.values()),
                          'collateral': counts['collateral']}), flush=True)
        for c in collateral[:int(os.environ.get('SHOW', '4'))]: print('    ' + c[:150], flush=True)
