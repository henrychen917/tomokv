#!/usr/bin/env python3
"""Offline compiler-budget trials for one object: compile POST with candidate --param sets and
classify every function body against PRE: intended (FLIP/fingerprint code), reloc-only (same
opcodes, moved anonymous constants) or collateral (an unrelated body's code changed).
Usage: trial.py <object> '<params>' ['<params>' ...]   (params replace existing --param flags)"""
import concurrent.futures as cf, json, os, re, shlex, subprocess, sys, hashlib
from pathlib import Path
WT = Path('/home/user/Projects/cx-flipfix')
sys.path.insert(0, str(WT / 'tools'))
import ccfix_audit  # noqa: F401
import lbstall_artifacts as audit
INTENDED = re.compile(
    r'IoLoop::(flip_control_pass|flip_io_drained|flip_candidate_clients_ready|flip_drop_closing_planned|'
    r'flip_io_drain_ordered|flip_close_held|activate|IoLoop\(\)|pubsub_disconnect_ready|'
    r'flip_fingerprint_finish_pass|parse_and_dispatch|r7_parse_and_dispatch)'
    r'|FlipFingerprintWriter::|FlipController::sample_fingerprint'
    r'|Server::(flip_build_client_plan|flip_complete_active|flip_begin|flip_client_quota|'
    r'flip_drop_planned_client|flip_forget_planned_client|signal_shutdown_pending|flip_client_at|'
    r'flip_client_destination)|on_signal'
    # Transitive: bodies that inline a changed function (IoLoop::activate's pin store in the role
    # thread lambdas; the close path's teardown gate).
    r'|_State_impl<std::thread::_Invoker<std::tuple<.*(run_fused_server|run_split_read_local_server|'
    r'run_fused_server_reordered|main::\{lambda|main\(int, char\*\*\)::\{lambda)|IoLoop::close_client'
    r'|IoLoop::init\(|ThreadCtx::init\(|flip_sweep_inbound|flip_reflag_inbound|flag_pending_io_inbound|IoLoop::prepare_client_transfer\(|client_transfers_quiesced')
SCRATCH = Path(os.environ.get('TRIALS', '/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/trials'))
obj = os.environ['TRIAL_OBJ']
def base_command():
    for line in (WT / 'build/flipfix/post-build.log').read_text().splitlines():
        if line.startswith('g++ ') and line.endswith(' -o build/' + obj):
            return shlex.split(line)
    raise SystemExit('no compile line')
def compile_with(params):
    argv = base_command()
    stripped = []
    skip = False
    for word in argv:
        if skip: skip = False; continue
        if word == '--param': skip = True; continue
        stripped.append(word)
    extra = shlex.split(params)
    i = stripped.index('-I.')
    argv = stripped[:i] + extra + stripped[i:]
    SRC = Path(os.environ.get('TRIAL_SRC', str(WT)))
    src_key = hashlib.sha1(b''.join(f.read_bytes() for f in sorted((SRC / 'src').rglob('*'))
                                    if f.is_file() and f.suffix in ('.h', '.inc', '.cc'))).hexdigest()[:10]
    tag = hashlib.sha1((obj + params + src_key).encode()).hexdigest()[:10]
    out = SCRATCH / (obj.replace('/', '_') + '.' + tag + '.o')
    out.parent.mkdir(parents=True, exist_ok=True)
    argv[argv.index('-o') + 1] = str(out)
    if not out.exists():
        subprocess.run(['taskset', '-c', '112-127', *argv], cwd=SRC, check=True)
    return params, out
def classify(path):
    a, b = audit.Elf(WT / 'build/flipfix/pre' / obj), audit.Elf(path)
    fa, fb = a.functions(), b.functions()
    names = sorted(set(fa) | set(fb))
    readable = dict(zip(names, subprocess.check_output(['c++filt'], input=('\n'.join(names) + '\n').encode()).decode().splitlines()))
    counts = {'equal': 0, 'intended': 0, 'reloc-only': 0, 'collateral': 0}
    collateral = []
    for n in names:
        if n in fa and n in fb:
            ca, cb = a.canonical(fa[n]), b.canonical(fb[n])
            if ca == cb: counts['equal'] += 1; continue
            kind = 'reloc-only' if ca[0] == cb[0] else 'code'
        else:
            kind = 'added' if n not in fa else 'removed'
        if INTENDED.search(readable[n]): counts['intended'] += 1
        elif kind == 'reloc-only': counts['reloc-only'] += 1
        else:
            counts['collateral'] += 1
            collateral.append(f"{kind}:{fa.get(n, {}).get('size', 0)}->{fb.get(n, {}).get('size', 0)} {readable[n][:110]}")
    return counts, collateral
